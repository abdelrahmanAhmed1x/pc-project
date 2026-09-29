package ai

import (
	"context"
	"iter"
	"strings"
	"testing"

	"google.golang.org/adk/v2/agent"
	"google.golang.org/adk/v2/model"
	"google.golang.org/adk/v2/runner"
	"google.golang.org/adk/v2/session"
	"google.golang.org/genai"
)

type runnerStub struct {
	events []*session.Event
	calls  int
	ids    []string
}

func (r *runnerStub) Run(_ context.Context, _, id string, _ *genai.Content, _ agent.RunConfig, _ ...runner.RunOption) iter.Seq2[*session.Event, error] {
	r.calls++
	r.ids = append(r.ids, id)
	return func(yield func(*session.Event, error) bool) {
		for _, event := range r.events {
			if !yield(event, nil) {
				return
			}
		}
	}
}

func textEvent(text string) *session.Event {
	return &session.Event{LLMResponse: model.LLMResponse{Content: genai.NewContentFromText(text, genai.RoleModel)}}
}

func TestChatCreatesAndResumesADKSessions(t *testing.T) {
	classifier := &runnerStub{events: []*session.Event{textEvent(`{"status":"valid","confidence":0.99,"reason":"buying"}`)}}
	assistant := &runnerStub{events: []*session.Event{textEvent(`{"message":"What is your budget?","product_ids":[]}`)}}
	service := &Service{sessions: session.InMemoryService(), classifier: classifier, assistant: assistant}
	first, err := service.Chat(context.Background(), ChatRequest{Message: "I need a GPU"})
	if err != nil || first.SessionID == "" || first.Message != "What is your budget?" || len(first.Products) != 0 {
		t.Fatalf("first chat: %+v %v", first, err)
	}
	second, err := service.Chat(context.Background(), ChatRequest{SessionID: first.SessionID, Message: "Around 35k"})
	if err != nil || second.SessionID != first.SessionID || classifier.calls != 2 || assistant.calls != 2 ||
		classifier.ids[1] != first.SessionID || assistant.ids[1] != first.SessionID {
		t.Fatalf("resumed chat: %+v err=%v classifier=%+v assistant=%+v", second, err, classifier, assistant)
	}
	if _, err := service.Chat(context.Background(), ChatRequest{SessionID: "bad", Message: "GPU"}); err == nil {
		t.Fatal("malformed session ID should be rejected")
	}
}

func TestChatRejectsInvalidDomainWithoutMainAgent(t *testing.T) {
	classifier := &runnerStub{events: []*session.Event{textEvent(`{"status":"invalid","confidence":0.99,"reason":"weather"}`)}}
	assistant := &runnerStub{}
	service := &Service{sessions: session.InMemoryService(), classifier: classifier, assistant: assistant}
	response, err := service.Chat(context.Background(), ChatRequest{Message: "What's the weather?"})
	if err != nil || response.Message != invalidDomainMessage || assistant.calls != 0 {
		t.Fatalf("invalid domain: %+v %v", response, err)
	}
	classifier.events = []*session.Event{textEvent(`{"status":"uncertain","confidence":0.6,"reason":"could be troubleshooting"}`)}
	response, err = service.Chat(context.Background(), ChatRequest{Message: "My computer is slow"})
	if err != nil || response.Message != uncertainDomainMessage || assistant.calls != 0 {
		t.Fatalf("uncertain domain: %+v %v", response, err)
	}
}

func TestChatOnlyReturnsToolProvenance(t *testing.T) {
	classifier := &runnerStub{events: []*session.Event{textEvent(`{"status":"valid","confidence":0.99,"reason":"product search"}`)}}
	toolResponse := &session.Event{LLMResponse: model.LLMResponse{Content: &genai.Content{Parts: []*genai.Part{{FunctionResponse: &genai.FunctionResponse{
		Name: "search_products", Response: map[string]any{"products": []map[string]any{{
			"id": 242, "name": "RX 9070", "price": "36500.00", "currency": "EGP", "in_stock": true,
			"provider": "sigma", "canonical_product_url": "https://retailer.example/242",
		}}},
	}}}}}}
	assistant := &runnerStub{events: []*session.Event{toolResponse, textEvent(`{"message":"Here are options.","product_ids":[999999,242]}`)}}
	service := &Service{sessions: session.InMemoryService(), classifier: classifier, assistant: assistant}
	response, err := service.Chat(context.Background(), ChatRequest{Message: "Find an RX 9070"})
	if err != nil || len(response.Products) != 1 || response.Products[0].ID != 242 ||
		response.Products[0].CanonicalProductURL != "https://retailer.example/242" {
		t.Fatalf("untrusted product leaked or real one missing: %+v %v", response, err)
	}
}

func TestDecodeFinalObjectAndClassificationValidation(t *testing.T) {
	var classification Classification
	if err := decodeFinalObject(`Reasoning first. {"status":"invalid","confidence":0.9,"reason":"weather"}`, &classification); err != nil || !classification.valid() {
		t.Fatalf("structured classifier fallback: %+v %v", classification, err)
	}
	if err := decodeFinalObject("```json\n{\"status\":\"valid\",\"confidence\":1,\"reason\":\"buying\"}\n```", &classification); err != nil || !classification.valid() {
		t.Fatalf("fenced structured output: %+v %v", classification, err)
	}
	for _, c := range []Classification{
		{Status: "other", Confidence: 0.9, Reason: "x"},
		{Status: ClassificationValid, Confidence: 1.1, Reason: "x"},
		{Status: ClassificationValid, Confidence: 0.9},
	} {
		if c.valid() {
			t.Fatalf("invalid classifier result accepted: %+v", c)
		}
	}
	if _, err := (&Service{sessions: session.InMemoryService()}).Chat(context.Background(), ChatRequest{Message: strings.Repeat("x", 4097)}); err == nil {
		t.Fatal("oversized message accepted")
	}
}

func TestParsePlainRecommendationIDs(t *testing.T) {
	message, ids := parsePlainRecommendation("Good for your stated use.\n\n**product_ids:** [242, 829]")
	if message != "Good for your stated use." || len(ids) != 2 || ids[0] != 242 || ids[1] != 829 {
		t.Fatalf("plain model output: %q %v", message, ids)
	}
	if _, ids := parsePlainRecommendation("No catalog IDs here: 242"); len(ids) != 0 {
		t.Fatalf("inferred an unlabeled product ID: %v", ids)
	}
	if message, ids := parsePlainRecommendation("No suitable match.\nproduct_ids: []"); message != "No suitable match." || len(ids) != 0 {
		t.Fatalf("explicit empty selection: %q %v", message, ids)
	}
}

func TestFallbackCandidatesAndAdviceSafety(t *testing.T) {
	stock, noStock := true, false
	grounded := groundedProducts{order: []int64{1, 2, 3, 4}, products: map[int64]CatalogProduct{
		1: {ID: 1, Price: "50000.00", Currency: "EGP", InStock: &stock},
		2: {ID: 2, Price: "30000.00", Currency: "EGP", InStock: &noStock},
		3: {ID: 3, Price: "32000.00", Currency: "EGP", InStock: &stock},
		4: {ID: 4, Price: "34000.00", Currency: "EGP", InStock: &stock},
	}}
	ids := fallbackCandidates("GPU around 35k", grounded, 1)
	if len(ids) != 1 || ids[0] != 3 {
		t.Fatalf("unsafe fallback set: %v", ids)
	}
	if !containsCatalogClaims("The cheapest one costs 36,500 EGP and is in stock") ||
		containsCatalogClaims("A stronger GPU may suit 1440p gaming") {
		t.Fatal("catalog prose safety check failed")
	}
	if got := safeAdvice("A stronger GPU may suit 1440p gaming.\nRX 9070 costs 36,500 EGP."); got != "A stronger GPU may suit 1440p gaming." {
		t.Fatalf("unsafe catalog claim survived: %q", got)
	}
}

func TestBuildCandidatesAndExactTotal(t *testing.T) {
	stock := true
	products := map[int64]CatalogProduct{}
	ids := make([]int64, 0, len(essentialBuildCategories)+1)
	for i, category := range essentialBuildCategories {
		id := int64(i + 1)
		products[id] = CatalogProduct{ID: id, Category: category, Price: "100.99", Currency: "EGP", InStock: &stock}
		ids = append(ids, id)
	}
	products[99] = CatalogProduct{ID: 99, Category: "gpu", Price: "1.00", Currency: "EGP", InStock: &stock}
	ids = append(ids, 99)
	selected := selectBuildCandidates(ids, products, true)
	if len(selected) != len(essentialBuildCategories) {
		t.Fatalf("expected one current listing per component: %v", selected)
	}
	if selected[1] != 99 {
		t.Fatalf("provisional build should choose cheaper returned GPU: %v", selected)
	}
	total := completeBuildTotal(selected, products)
	if total == nil || total.Amount != "606.94" || total.Currency != "EGP" {
		t.Fatalf("wrong exact build total: %+v", total)
	}
	if completeBuildTotal(selected[:len(selected)-1], products) != nil {
		t.Fatal("incomplete build must not have a total")
	}
	products[1] = CatalogProduct{ID: 1, Category: "cpu", Price: "100.991", Currency: "EGP", InStock: &stock}
	if completeBuildTotal(selected, products) != nil {
		t.Fatal("invalid decimal price must not be totaled")
	}
}

func TestBudgetParsing(t *testing.T) {
	for input, expected := range map[string]int64{
		"gaming PC around 50k": 5_000_000,
		"budget 50000 EGP":     5_000_000,
		"50k and 1440p":        5_000_000,
		"1440p gaming":         0,
	} {
		if got := budgetFromMessage(input); got != expected {
			t.Errorf("%q: got %d, want %d", input, got, expected)
		}
	}
}

func TestHardBudgetParsing(t *testing.T) {
	for input, want := range map[string]int64{
		"GPU under 35000":    3_500_000,
		"SSD below 7k":       700_000,
		"PSU up to 2500 EGP": 250_000,
		"GPU around 35k":     0,
	} {
		if got := hardBudgetFromMessage(input); got != want {
			t.Errorf("%q: got %d want %d", input, got, want)
		}
	}
}
