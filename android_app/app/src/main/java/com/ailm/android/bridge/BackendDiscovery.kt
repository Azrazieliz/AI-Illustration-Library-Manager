package com.ailm.android.bridge

import okhttp3.OkHttpClient
import okhttp3.Request
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.net.InetAddress
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

object BackendDiscovery {

    private const val FALLBACK_URL = "http://192.168.1.40:8000"

    private val discoveryScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @Volatile
    private var cachedUrl: String? = null

    @Volatile
    private var manualUrl: String? = null

    @Volatile
    private var discoveryStarted: Boolean = false

    fun getConfiguredBaseUrl(): String? = manualUrl

    fun setConfiguredBaseUrl(url: String?) {
        manualUrl = url?.trim()?.takeIf { it.isNotBlank() }
        if (manualUrl != null) {
            cachedUrl = manualUrl
        }
    }

    fun getBaseUrl(): String {
        manualUrl?.let { return it }
        cachedUrl?.let { return it }

        return FALLBACK_URL
    }

    fun startDiscovery(onDiscovered: ((String) -> Unit)? = null) {
        if (manualUrl != null) {
            onDiscovered?.invoke(manualUrl!!)
            return
        }
        if (cachedUrl != null) {
            onDiscovered?.invoke(cachedUrl!!)
            return
        }
        if (discoveryStarted) {
            return
        }
        discoveryStarted = true

        discoveryScope.launch {
            try {
                val discovered = discoverBaseUrl()
                if (!discovered.isNullOrBlank()) {
                    cachedUrl = discovered
                    onDiscovered?.invoke(discovered!!)
                }
            } finally {
                discoveryStarted = false
            }
        }
    }

    private fun discoverBaseUrl(): String? {
        val prefix = localSubnet() ?: return null

        val client = OkHttpClient.Builder()
            .connectTimeout(300, TimeUnit.MILLISECONDS)
            .readTimeout(300, TimeUnit.MILLISECONDS)
            .build()

        val executor = Executors.newFixedThreadPool(32)

        val results = ConcurrentLinkedQueue<String>()

        for (i in 1..254) {

            val ip = "$prefix.$i"

            executor.submit {

                try {

                    val request = Request.Builder()
                        .url("http://$ip:8000/health")
                        .build()

                    client.newCall(request).execute().use {

                        if (it.isSuccessful) {
                            results.add("http://$ip:8000")
                        }
                    }

                } catch (_: Exception) {
                }

            }
        }

        executor.shutdown()

        executor.awaitTermination(10, TimeUnit.SECONDS)

        return results.firstOrNull()
    }

    private fun localSubnet(): String? {
        val address = InetAddress.getLocalHost().hostAddress ?: return null

        val pieces = address.split('.')

        if (pieces.size != 4)
            return null

        return pieces.take(3).joinToString(".")
    }
}