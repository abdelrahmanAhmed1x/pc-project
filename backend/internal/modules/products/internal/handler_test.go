package internal

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/abdelrahmanAhmed1x/core/logger"
	"github.com/abdelrahmanAhmed1x/core/pagination"
	"github.com/gin-gonic/gin"
)

type serviceStub struct {
	options     ListProductsQuery
	id          int64
	searchQuery string
	searchLimit int
	searchPage  int
	emptySearch bool
}

func (*serviceStub) Categories(context.Context) ([]Category, error) { return []Category{}, nil }
func (*serviceStub) Providers(context.Context) ([]Provider, error)  { return []Provider{}, nil }
func (*serviceStub) Brands(context.Context) ([]Brand, error)        { return []Brand{}, nil }
func (s *serviceStub) Get(_ context.Context, id int64) (ProductDetail, error) {
	s.id = id
	return ProductDetail{Product: Product{ID: id}}, nil
}
func (s *serviceStub) List(_ context.Context, options ListProductsQuery) (pagination.Result[Product], error) {
	s.options = options
	return pagination.NewResult([]Product{}, 0, options.Query), nil
}
func (s *serviceStub) Search(_ context.Context, query string, page pagination.Query) (pagination.Result[Product], error) {
	s.searchQuery, s.searchLimit, s.searchPage = query, page.Limit, page.Page
	if s.emptySearch {
		return pagination.NewResult([]Product{}, 0, page), nil
	}
	return pagination.NewResult([]Product{{ID: 9, Name: "GPU"}}, 25, page), nil
}

func TestHandlerBindsFiltersAndRoutes(t *testing.T) {
	gin.SetMode(gin.TestMode)
	service := &serviceStub{}
	router := gin.New()
	RegisterRoutes(router, NewHandler(service, logger.New(logger.Config{Output: io.Discard})))
	req := httptest.NewRequest(http.MethodGet, "/products?category_ids=1&category_ids=2&provider_ids=3&brand_ids=4&min_price=100.50&max_price=200&in_stock=false&sort=price_desc&page=2&limit=25", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("list status: %d body: %s", w.Code, w.Body.String())
	}
	if len(service.options.CategoryIDs) != 2 || service.options.CategoryIDs[0] != 1 || service.options.CategoryIDs[1] != 2 ||
		len(service.options.ProviderIDs) != 1 || service.options.ProviderIDs[0] != 3 ||
		len(service.options.BrandIDs) != 1 || service.options.BrandIDs[0] != 4 ||
		service.options.MinPrice != "100.50" || service.options.MaxPrice != "200" ||
		service.options.InStock == nil || *service.options.InStock || service.options.Sort != "price_desc" ||
		service.options.Query.Page != 2 || service.options.Query.Limit != 25 {
		t.Fatalf("incorrect list options: %+v", service.options)
	}
	var envelope map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &envelope); err != nil || envelope["success"] != true {
		t.Fatalf("invalid response: %s: %v", w.Body.String(), err)
	}

	req = httptest.NewRequest(http.MethodGet, "/products", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK || service.options.Query.Page != 1 || service.options.Query.Limit != 10 {
		t.Fatalf("default pagination: status=%d query=%+v", w.Code, service.options.Query)
	}

	req = httptest.NewRequest(http.MethodGet, "/products?q=rtx&category_ids=1,2&brand_ids=4,7&page_size=20", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK || service.options.Search != "rtx" || service.options.PageSize != 20 ||
		len(service.options.CategoryIDs) != 2 || service.options.CategoryIDs[1] != 2 ||
		len(service.options.BrandIDs) != 2 || service.options.BrandIDs[1] != 7 {
		t.Fatalf("comma filters and page_size: status=%d options=%+v", w.Code, service.options)
	}

	req = httptest.NewRequest(http.MethodGet, "/products/42", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK || service.id != 42 {
		t.Fatalf("get status=%d id=%d", w.Code, service.id)
	}

	req = httptest.NewRequest(http.MethodGet, "/products/search?q=rtx&page=2&limit=5", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	var searchResponse struct {
		Data []Product       `json:"data"`
		Meta pagination.Meta `json:"meta"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &searchResponse); err != nil || w.Code != http.StatusOK ||
		service.searchQuery != "rtx" || service.searchPage != 2 || service.searchLimit != 5 ||
		searchResponse.Meta.Page != 2 || searchResponse.Meta.Limit != 5 ||
		searchResponse.Meta.TotalItems != 25 || searchResponse.Meta.TotalPages != 5 ||
		len(searchResponse.Data) != 1 || searchResponse.Data[0].ID != 9 {
		t.Fatalf("search route: status=%d body=%s err=%v", w.Code, w.Body.String(), err)
	}
	req = httptest.NewRequest(http.MethodGet, "/products/search?q=rtx", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK || service.searchPage != 1 || service.searchLimit != 10 {
		t.Fatalf("default search page: status=%d body=%s", w.Code, w.Body.String())
	}
	req = httptest.NewRequest(http.MethodGet, "/products/search", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("missing search q status=%d", w.Code)
	}
	service.emptySearch = true
	req = httptest.NewRequest(http.MethodGet, "/products/search?q=unknown", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), `"data":[]`) {
		t.Fatalf("empty search should return a list: status=%d body=%s", w.Code, w.Body.String())
	}
	req = httptest.NewRequest(http.MethodGet, "/products/search?q=rtx&limit=101", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("invalid search limit status=%d", w.Code)
	}

	req = httptest.NewRequest(http.MethodGet, "/products?limit=101", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("invalid limit status=%d", w.Code)
	}
}
