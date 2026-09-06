package com.krausstt.freeagent

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL
import java.util.zip.GZIPInputStream

/**
 * FreeAgent: a WebView shell around the dashboard, with ESPN fetched natively.
 *
 * The native fetch is the entire point. ESPN's API sends no CORS headers, so a
 * page loaded from file:// cannot call it from JavaScript. Kotlin has no such
 * restriction, so the bridge does the request and hands the JSON to the page.
 * That is also why this app needs no backend: the phone talks to ESPN directly.
 */
class MainActivity : Activity() {

    private lateinit var web: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true          // the page persists its checklist here
            settings.databaseEnabled = true
            settings.loadWithOverviewMode = false
            settings.useWideViewPort = false           // honour the page's own viewport meta
            settings.textZoom = 100
            webViewClient = WebViewClient()
            addJavascriptInterface(Bridge(this@MainActivity), "Native")
        }
        setContentView(web)
        web.loadUrl("file:///android_asset/index.html")
    }

    /** Called from a worker thread; marshals back onto the UI thread for the WebView. */
    fun resolve(callback: String, payload: String) {
        runOnUiThread {
            web.evaluateJavascript("window.$callback(${JSONObject.quote(payload)})", null)
        }
    }

    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}

private const val PREFS = "freeagent"
private const val UA =
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) " +
        "Chrome/126.0.0.0 Mobile Safari/537.36"

class Bridge(private val activity: MainActivity) {

    private val prefs = activity.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    // ---------------------------------------------------------------- config

    @JavascriptInterface
    fun getConfig(): String = prefs.getString("config", "{}") ?: "{}"

    @JavascriptInterface
    fun setConfig(json: String) {
        prefs.edit().putString("config", json).apply()
    }

    // --------------------------------------------------------------- journal

    /**
     * Append one decision record. Stored as newline-delimited JSON so a partial
     * write can never corrupt earlier entries -- this log is the one thing here
     * that cannot be regenerated from ESPN.
     */
    @JavascriptInterface
    fun appendJournal(entry: String) {
        val existing = prefs.getString("journal", "") ?: ""
        val line = entry.replace("\n", " ")
        prefs.edit().putString("journal", if (existing.isEmpty()) line else "$existing\n$line").apply()
    }

    @JavascriptInterface
    fun getJournal(): String = prefs.getString("journal", "") ?: ""

    // --------------------------------------------------------------- network

    /**
     * Fetch a league view from ESPN. Asynchronous because Android forbids
     * network on the main thread, and a @JavascriptInterface method runs on a
     * WebView thread that must not block. The page supplies a callback name.
     */
    @JavascriptInterface
    fun fetchLeague(leagueId: String, season: String, views: String, callback: String) {
        Thread {
            val payload = try {
                val query = views.split(",")
                    .filter { it.isNotBlank() }
                    .joinToString("&") { "view=" + it.trim() }
                val url = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl" +
                    "/seasons/$season/segments/0/leagues/$leagueId?$query"
                val body = httpGet(url, cookiesFromConfig())
                JSONObject().put("ok", true).put("data", JSONObject(body)).toString()
            } catch (t: Throwable) {
                JSONObject().put("ok", false)
                    .put("error", t.message ?: t.javaClass.simpleName).toString()
            }
            activity.resolve(callback, payload)
        }.start()
    }

    /** NFL team schedules, from which the page derives bye weeks. */
    @JavascriptInterface
    fun fetchSeason(season: String, views: String, callback: String) {
        Thread {
            val payload = try {
                val query = views.split(",").filter { it.isNotBlank() }
                    .joinToString("&") { "view=" + it.trim() }
                val url = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl" +
                    "/seasons/$season?$query"
                val body = httpGet(url, cookiesFromConfig())
                JSONObject().put("ok", true).put("data", JSONObject(body)).toString()
            } catch (t: Throwable) {
                JSONObject().put("ok", false)
                    .put("error", t.message ?: t.javaClass.simpleName).toString()
            }
            activity.resolve(callback, payload)
        }.start()
    }

    private fun cookiesFromConfig(): String? {
        return try {
            val cfg = JSONObject(getConfig())
            val s2 = cfg.optString("espn_s2", "")
            val swid = cfg.optString("swid", "")
            if (s2.isBlank() || swid.isBlank()) null
            else "espn_s2=$s2; SWID=" + if (swid.startsWith("{")) swid else "{${swid.trim('{', '}')}}"
        } catch (_: Throwable) { null }
    }

    private fun httpGet(url: String, cookie: String?): String {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 15_000
            readTimeout = 25_000
            setRequestProperty("User-Agent", UA)
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Accept-Encoding", "gzip")
            if (cookie != null) setRequestProperty("Cookie", cookie)
        }
        try {
            val code = conn.responseCode
            if (code == 401 || code == 403) {
                throw IllegalStateException(
                    "ESPN returned $code. A private league needs espn_s2 and SWID in Settings."
                )
            }
            if (code != 200) throw IllegalStateException("ESPN returned HTTP $code")

            val raw = conn.inputStream
            val stream = if ("gzip".equals(conn.contentEncoding, ignoreCase = true))
                GZIPInputStream(raw) else raw
            return stream.bufferedReader().use(BufferedReader::readText)
        } finally {
            conn.disconnect()
        }
    }
}
