package com.autoasr.app

import android.content.Context
import android.net.Uri

object ServerPrefs {
    private const val PREFS = "auto_asr"
    private const val KEY_URL = "server_url"

    fun getUrl(context: Context): String {
        val stored = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_URL, null)
            ?.trim()
            .orEmpty()
        if (stored.isNotEmpty()) return stored.trimEnd('/')
        return context.getString(R.string.default_server_url).trimEnd('/')
    }

    fun setUrl(context: Context, url: String) {
        val cleaned = url.trim().trimEnd('/')
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_URL, cleaned)
            .apply()
    }

    fun hostMatches(context: Context, host: String?): Boolean {
        if (host.isNullOrBlank()) return false
        return try {
            val configured = Uri.parse(getUrl(context)).host?.lowercase()
            configured != null && configured == host.lowercase()
        } catch (_: Exception) {
            false
        }
    }
}
