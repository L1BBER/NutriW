package com.example.nutriw.data.api

data class ScanResponse(
    val products: List<ProductItem> = emptyList(),
    val recipes: List<RecipeItem> = emptyList(),
    val warnings: List<String> = emptyList(),
    val need_user_review: Boolean? = null
)

data class ProductItem(
    val name: String,
    val brand: String? = null,
    val amount: String? = null,      // "500 ml", "2 szt", "300 g"
    val kcal: Double? = null,
    val protein: Double? = null,
    val fat: Double? = null,
    val carbs: Double? = null,
    val confidence: Double? = null
)

data class RecipeItem(
    val titlePl: String,
    val missing: List<String> = emptyList(),
    val kcalPerPortion: Double? = null
)

data class ConfirmProductsRequest(
    val products: List<EditableProductPayload>
)

data class EditableProductPayload(
    val name: String,
    val amount: String? = null
)

data class ConfirmProductsResponse(
    val recipes: List<RecipeItem> = emptyList()
)
