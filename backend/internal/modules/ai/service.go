package ai

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"iter"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/google/uuid"
	"google.golang.org/adk/v2/agent"
	"google.golang.org/adk/v2/runner"
	"google.golang.org/adk/v2/session"
	"google.golang.org/genai"
)

const (
	assistantApp  = "technology_buying_assistant"
	classifierApp = "technology_buying_classifier"
	guestUser     = "anonymous" // Session IDs are unguessable bearer tokens until auth is added.
)

const invalidDomainMessage = "I can help you choose, compare, and find technology products. Tell me what you want to buy, your budget, and how you will use it."
const uncertainDomainMessage = "Are you looking to buy or upgrade technology, or troubleshoot something you already own?"

type eventRunner interface {
	Run(context.Context, string, string, *genai.Content, agent.RunConfig, ...runner.RunOption) iter.Seq2[*session.Event, error]
}

type Service struct {
	sessions   session.Service
	classifier eventRunner
	assistant  eventRunner
}

func newService(sessions session.Service, classifier, assistant *runner.Runner) *Service {
	return &Service{sessions: sessions, classifier: classifier, assistant: assistant}
}

func (s *Service) Chat(ctx context.Context, req ChatRequest) (ChatResponse, error) {
	message := strings.TrimSpace(req.Message)
	if message == "" || len(message) > 4096 {
		return ChatResponse{}, fmt.Errorf("%w: message must contain 1 to 4096 bytes", ErrInvalidRequest)
	}
	if req.SessionID != "" {
		if _, err := uuid.Parse(req.SessionID); err != nil {
			return ChatResponse{}, fmt.Errorf("%w: malformed session_id", ErrInvalidRequest)
		}
	}
	sessionID, err := s.resolveSession(ctx, req.SessionID)
	if err != nil {
		return ChatResponse{}, err
	}
	response := ChatResponse{SessionID: sessionID, Products: []RecommendedProduct{}}
	classification, err := s.classify(ctx, sessionID, message)
	if err != nil {
		return ChatResponse{}, err
	}
	switch classification.Status {
	case ClassificationInvalid:
		response.Message = invalidDomainMessage
		return response, nil
	case ClassificationUncertain:
		response.Message = uncertainDomainMessage
		return response, nil
	}
	build, budget, err := s.shoppingState(ctx, sessionID, message)
	if err != nil {
		return ChatResponse{}, err
	}
	answer, grounded, interrupted, err := runAssistant(ctx, s.assistant, sessionID, message, build, budget)
	if err != nil {
		return ChatResponse{}, fmt.Errorf("%w: assistant run: %v", ErrUnavailable, err)
	}
	response.Message = strings.TrimSpace(answer.Message)
	if build {
		answer.ProductIDs = selectBuildCandidates(answer.ProductIDs, grounded, interrupted)
	}
	if wantsCheapest(message) {
		ids := answer.ProductIDs[:0]
		for _, id := range answer.ProductIDs {
			if product, ok := grounded[id]; ok && product.InStock != nil && *product.InStock {
				ids = append(ids, id)
			}
		}
		answer.ProductIDs = ids
		sort.SliceStable(answer.ProductIDs, func(i, j int) bool {
			left, _ := strconv.ParseFloat(grounded[answer.ProductIDs[i]].Price, 64)
			right, _ := strconv.ParseFloat(grounded[answer.ProductIDs[j]].Price, 64)
			return left < right
		})
	}
	if build {
		response.EstimatedTotal = completeBuildTotal(answer.ProductIDs, grounded)
		if interrupted && len(answer.ProductIDs) > 0 {
			if response.EstimatedTotal == nil {
				response.Message = "I found current listings for some components, but I could not assemble a complete build yet. These are individual candidates, not a build to buy as-is."
			} else {
				response.Message = "These are preliminary catalog candidates for your build, not a compatibility-verified parts list."
			}
		}
		if response.EstimatedTotal != nil {
			response.Message += fmt.Sprintf(" Estimated catalog total: %s %s.", response.EstimatedTotal.Amount, response.EstimatedTotal.Currency)
			if budget > 0 && response.EstimatedTotal.Currency == "EGP" {
				total, _ := priceInCents(response.EstimatedTotal.Amount)
				if total > budget {
					response.Message += fmt.Sprintf(" This provisional set exceeds your budget by %d.%02d EGP; these are not a build to buy as-is.", (total-budget)/100, (total-budget)%100)
				} else {
					response.Message += fmt.Sprintf(" It is %d.%02d EGP below your budget.", (budget-total)/100, (budget-total)%100)
				}
			}
			response.Message += " Component compatibility still needs checking."
		}
	}
	for _, id := range answer.ProductIDs {
		product, ok := grounded[id]
		if !ok {
			continue // Never trust an ID or URL supplied only by the model.
		}
		response.Products = append(response.Products, RecommendedProduct{
			ID: product.ID, Name: product.Name, Price: product.Price,
			Currency: product.Currency, InStock: product.InStock, Provider: product.Provider,
			CanonicalProductURL: product.CanonicalProductURL, ImageURL: product.ImageURL,
		})
		delete(grounded, id) // Do not repeat one listing in the response.
	}
	if response.Message == "" {
		return ChatResponse{}, fmt.Errorf("%w: assistant returned an empty message", ErrUnavailable)
	}
	if interrupted {
		if err := s.recordAssistantReply(ctx, sessionID, response.Message); err != nil {
			return ChatResponse{}, err
		}
	}
	return response, nil
}

var essentialBuildCategories = []string{"cpu", "gpu", "motherboard", "ram", "ssd", "power_supply", "case"}

func selectBuildCandidates(ids []int64, grounded map[int64]CatalogProduct, cheapest bool) []int64 {
	selected := make([]int64, 0, len(ids))
	categoryIndex := make(map[string]int)
	for _, id := range ids {
		product, ok := grounded[id]
		if !ok || product.Category == "" {
			continue
		}
		if product.InStock == nil || !*product.InStock {
			continue
		}
		if index, exists := categoryIndex[product.Category]; exists {
			if cheapest {
				current, currentErr := priceInCents(grounded[selected[index]].Price)
				candidate, candidateErr := priceInCents(product.Price)
				if currentErr == nil && candidateErr == nil && candidate < current {
					selected[index] = id
				}
			}
			continue
		}
		categoryIndex[product.Category] = len(selected)
		selected = append(selected, id)
	}
	return selected
}

// A total is useful only when every essential component has a current listing.
// Decimal prices are summed in cents to avoid floating-point money arithmetic.
func completeBuildTotal(ids []int64, grounded map[int64]CatalogProduct) *Money {
	if len(ids) == 0 {
		return nil
	}
	seen := make(map[string]bool)
	var total int64
	var currency string
	for _, id := range ids {
		product, ok := grounded[id]
		if !ok || product.Category == "" || seen[product.Category] {
			return nil
		}
		if product.InStock == nil || !*product.InStock {
			return nil
		}
		if currency == "" {
			currency = product.Currency
		} else if product.Currency != currency {
			return nil
		}
		amount, err := priceInCents(product.Price)
		if err != nil || amount < 0 || total > (int64(^uint64(0)>>1)-amount) {
			return nil
		}
		total += amount
		seen[product.Category] = true
	}
	for _, category := range essentialBuildCategories {
		if !seen[category] {
			return nil
		}
	}
	return &Money{Amount: fmt.Sprintf("%d.%02d", total/100, total%100), Currency: currency}
}

func priceInCents(price string) (int64, error) {
	whole, fraction, hasDecimal := strings.Cut(price, ".")
	if !hasDecimal {
		fraction = "00"
	}
	if len(fraction) == 1 {
		fraction += "0"
	}
	if whole == "" || len(fraction) != 2 {
		return 0, errors.New("invalid price")
	}
	major, err := strconv.ParseInt(whole, 10, 64)
	if err != nil || major < 0 || major > (int64(^uint64(0)>>1)-99)/100 {
		return 0, errors.New("invalid price")
	}
	minor, err := strconv.ParseInt(fraction, 10, 64)
	if err != nil || minor < 0 || minor > 99 {
		return 0, errors.New("invalid price")
	}
	return major*100 + minor, nil
}

func (s *Service) shoppingState(ctx context.Context, id, message string) (bool, int64, error) {
	current, err := s.sessions.Get(ctx, &session.GetRequest{AppName: assistantApp, UserID: guestUser, SessionID: id})
	if err != nil {
		return false, 0, fmt.Errorf("%w: get shopping context: %v", ErrUnavailable, err)
	}
	intent, err := current.Session.State().Get("shopping_intent")
	build := buildRequest(message) || (err == nil && intent == "build")
	if !build {
		return false, 0, nil
	}
	if budget := budgetFromMessage(message); budget > 0 {
		return true, budget, nil
	}
	stored, err := current.Session.State().Get("budget_egp_cents")
	if err == nil {
		switch value := stored.(type) {
		case int64:
			return true, value, nil
		case float64:
			return true, int64(value), nil
		}
	}
	return true, 0, nil
}

func (s *Service) recordAssistantReply(ctx context.Context, id, message string) error {
	current, err := s.sessions.Get(ctx, &session.GetRequest{AppName: assistantApp, UserID: guestUser, SessionID: id})
	if err != nil {
		return fmt.Errorf("%w: get session for reply: %v", ErrUnavailable, err)
	}
	event := session.NewEvent(ctx, "")
	event.Author = "technology_buying_assistant"
	event.Content = genai.NewContentFromText(message, genai.RoleModel)
	if err := s.sessions.AppendEvent(ctx, current.Session, event); err != nil {
		return fmt.Errorf("%w: save assistant reply: %v", ErrUnavailable, err)
	}
	return nil
}

func (s *Service) resolveSession(ctx context.Context, id string) (string, error) {
	if id == "" {
		created, err := s.sessions.Create(ctx, &session.CreateRequest{AppName: assistantApp, UserID: guestUser})
		if err != nil {
			return "", fmt.Errorf("%w: create session: %v", ErrUnavailable, err)
		}
		id = created.Session.ID()
		if _, err := s.sessions.Create(ctx, &session.CreateRequest{AppName: classifierApp, UserID: guestUser, SessionID: id}); err != nil {
			_ = s.sessions.Delete(ctx, &session.DeleteRequest{AppName: assistantApp, UserID: guestUser, SessionID: id})
			return "", fmt.Errorf("%w: create classifier session: %v", ErrUnavailable, err)
		}
		return id, nil
	}
	for _, app := range []string{assistantApp, classifierApp} {
		if _, err := s.sessions.Get(ctx, &session.GetRequest{AppName: app, UserID: guestUser, SessionID: id}); err != nil {
			if errors.Is(err, session.ErrNotFound) {
				return "", ErrSessionNotFound
			}
			return "", fmt.Errorf("%w: get session: %v", ErrUnavailable, err)
		}
	}
	return id, nil
}

func (s *Service) classify(ctx context.Context, id, message string) (Classification, error) {
	for attempt := 0; attempt < 2; attempt++ {
		input := message
		if attempt == 1 {
			input = "Classify the previous user request again. Return only the required structured result."
		}
		text, _, _, err := runAgent(ctx, s.classifier, id, input, 0)
		if err != nil {
			return Classification{}, fmt.Errorf("%w: classifier run: %v", ErrUnavailable, err)
		}
		var result Classification
		if err := decodeFinalObject(text, &result); err == nil && result.valid() {
			return result, nil
		}
	}
	return Classification{}, fmt.Errorf("%w: invalid classifier output", ErrUnavailable)
}

func runAssistant(ctx context.Context, r eventRunner, id, message string, build bool, budget int64) (assistantAnswer, map[int64]CatalogProduct, bool, error) {
	maxTools := 2
	if build {
		maxTools = 8
	}
	var opts []runner.RunOption
	state := make(map[string]any)
	if buildRequest(message) {
		state["shopping_intent"] = "build"
	}
	if build && budget > 0 {
		state["budget_egp_cents"] = budget
	}
	if len(state) > 0 {
		opts = append(opts, runner.WithStateDelta(state))
	}
	text, grounded, interrupted, err := runAgent(ctx, r, id, message, maxTools, opts...)
	if err != nil {
		return assistantAnswer{}, nil, false, err
	}
	var answer assistantAnswer
	if err := decodeFinalObject(text, &answer); err != nil {
		// The local OpenAI-compatible server can ignore ADK's final-output
		// schema. Plain follow-up questions remain useful; catalog claims are
		// assembled only from captured tool results.
		answer.Message = text
		for _, product := range grounded.order {
			answer.ProductIDs = append(answer.ProductIDs, product)
		}
		if len(grounded.order) > 0 {
			answer.Message = "Here are matching products from the current catalog. Their prices, stores, stock, and purchase links are shown in the product list."
		}
	}
	if interrupted && build && len(grounded.order) > 0 {
		answer.ProductIDs = grounded.order
	}
	return answer, grounded.products, interrupted, nil
}

func buildRequest(message string) bool {
	text := strings.ToLower(message)
	return strings.Contains(text, "build") || strings.Contains(text, "gaming pc") || strings.Contains(text, "pc setup")
}

var budgetPattern = regexp.MustCompile(`(?i)\b(\d+(?:\.\d+)?)\s*k\b|\b(?:budget|around|about|under|up to)\s*(?:of\s*)?(\d{4,6})\b`)

func budgetFromMessage(message string) int64 {
	match := budgetPattern.FindStringSubmatch(message)
	if match == nil {
		return 0
	}
	amount := match[1]
	multiplier := float64(100)
	if amount != "" {
		multiplier = 100000
	} else {
		amount = match[2]
	}
	value, err := strconv.ParseFloat(amount, 64)
	if err != nil || value <= 0 || value > 10_000_000 {
		return 0
	}
	return int64(math.Round(value * multiplier))
}

// Some OpenAI-compatible servers ignore response-format constraints. ADK still
// supplies the schema; this accepts a trailing JSON object and validates it.
func decodeFinalObject(text string, out any) error {
	var candidate string
	end := -1
	start, depth, inString, escaped := -1, 0, false, false
	for i, char := range text {
		switch {
		case escaped:
			escaped = false
		case inString && char == '\\':
			escaped = true
		case char == '"':
			inString = !inString
		case !inString && char == '{':
			if depth == 0 {
				start = i
			}
			depth++
		case !inString && char == '}' && depth > 0:
			depth--
			if depth == 0 {
				candidate = text[start : i+1]
				end = i + 1
			}
		}
	}
	if candidate == "" || strings.TrimSpace(text[end:]) != "" {
		return errors.New("no JSON object in final response")
	}
	return json.Unmarshal([]byte(candidate), out)
}

type groundedProducts struct {
	products map[int64]CatalogProduct
	order    []int64
}

func runAgent(ctx context.Context, r eventRunner, id, message string, maxToolResponses int, opts ...runner.RunOption) (string, groundedProducts, bool, error) {
	grounded := groundedProducts{products: make(map[int64]CatalogProduct)}
	var final string
	toolResponses := 0
	interrupted := false
	for event, err := range r.Run(ctx, guestUser, id, genai.NewContentFromText(message, genai.RoleUser), agent.RunConfig{}, opts...) {
		if err != nil {
			return "", groundedProducts{}, false, err
		}
		if event == nil || event.Content == nil {
			continue
		}
		for _, part := range event.Content.Parts {
			if part == nil {
				continue
			}
			if fr := part.FunctionResponse; fr != nil {
				if (fr.Name == "search_products" || fr.Name == "get_product") && fr.Response != nil {
					if message, ok := fr.Response["error"].(string); ok && message != "" {
						return "", groundedProducts{}, false, fmt.Errorf("catalog tool %s: %s", fr.Name, message)
					}
				}
				captureProducts(&grounded, fr)
				if fr.Name == "search_products" || fr.Name == "get_product" {
					toolResponses++
				}
			}
			if event.IsFinalResponse() && part.Text != "" {
				final += part.Text
			}
		}
		if maxToolResponses > 0 && toolResponses >= maxToolResponses {
			interrupted = strings.TrimSpace(final) == ""
			break
		}
	}
	if strings.TrimSpace(final) == "" {
		if !interrupted {
			return "", groundedProducts{}, false, errors.New("agent returned no final response")
		}
		final = "I couldn't find a current matching listing in the catalog. Try a more specific product model or category."
	}
	return final, grounded, interrupted, nil
}

func captureProducts(found *groundedProducts, response *genai.FunctionResponse) {
	if response.Name != "search_products" && response.Name != "get_product" {
		return
	}
	raw, err := json.Marshal(response.Response)
	if err != nil {
		return
	}
	var envelope struct {
		Products []CatalogProduct `json:"products"`
		Product  *CatalogProduct  `json:"product"`
		Result   json.RawMessage  `json:"result"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return
	}
	if len(envelope.Result) > 0 {
		_ = json.Unmarshal(envelope.Result, &envelope)
	}
	if envelope.Product != nil {
		envelope.Products = append(envelope.Products, *envelope.Product)
	}
	for _, product := range envelope.Products {
		if product.ID > 0 && product.CanonicalProductURL != "" {
			if _, exists := found.products[product.ID]; !exists {
				found.order = append(found.order, product.ID)
			}
			found.products[product.ID] = product
		}
	}
}
