package typesense

import (
	"encoding/json"
	"testing"
)

func TestProductSchemaMatchesDocumentAndNulls(t *testing.T) {
	schema := productSchema()
	if schema.Name != "products" {
		t.Fatalf("collection name = %q", schema.Name)
	}
	fields := make(map[string]bool, len(schema.Fields))
	for _, field := range schema.Fields {
		fields[field.Name] = field.Optional != nil && *field.Optional
		if field.Name == "category_slug" || field.Name == "provider_name" {
			if field.Index != nil && !*field.Index {
				t.Errorf("%s must be searchable", field.Name)
			}
		}
	}
	raw, err := json.Marshal(ProductDocument{ID: "829", ProductID: 829})
	if err != nil {
		t.Fatal(err)
	}
	var document map[string]any
	if err := json.Unmarshal(raw, &document); err != nil {
		t.Fatal(err)
	}
	if document["id"] != "829" {
		t.Fatalf("document id = %v", document["id"])
	}
	for field := range document {
		if field != "id" {
			if _, ok := fields[field]; !ok {
				t.Errorf("document field %q missing from schema", field)
			}
		}
	}
	for _, name := range []string{"brand_id", "brand_name", "price", "in_stock", "image_url"} {
		if !fields[name] {
			t.Errorf("%s must be optional", name)
		}
		if _, ok := document[name]; ok {
			t.Errorf("null %s should be omitted", name)
		}
	}
}
