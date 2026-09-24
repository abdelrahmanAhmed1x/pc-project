package internal

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/abdelrahmanAhmed1x/core/logger"
	"github.com/abdelrahmanAhmed1x/core/pagination"
	"github.com/gin-gonic/gin"
)

type serviceStub struct {
	options ListProductsQuery
	id      int64
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

	req = httptest.NewRequest(http.MethodGet, "/products/42", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK || service.id != 42 {
		t.Fatalf("get status=%d id=%d", w.Code, service.id)
	}

	req = httptest.NewRequest(http.MethodGet, "/products?limit=101", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("invalid limit status=%d", w.Code)
	}
}
