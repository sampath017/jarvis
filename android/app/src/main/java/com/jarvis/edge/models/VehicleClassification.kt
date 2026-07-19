package com.jarvis.edge.models

data class VehicleClassification(
    val vehicleClass: String,
    val confidence: Double,
    val isMatch: Boolean
)
