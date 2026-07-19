package com.jarvis.edge.data.remote

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST

interface JarvisApi {

    @POST("v1/context-events")
    suspend fun sendContextEvent(
        @Header("X-Authorization") authHeader: String,
        @Header("X-Firebase-AppCheck") appCheckHeader: String?,
        @Body request: ContextEventRequest
    ): Response<APIResponse>

    @POST("v1/commands")
    suspend fun sendCommand(
        @Header("X-Authorization") authHeader: String,
        @Header("X-Firebase-AppCheck") appCheckHeader: String?,
        @Body request: CommandRequest
    ): Response<APIResponse>
}
