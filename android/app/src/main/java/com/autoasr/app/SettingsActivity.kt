package com.autoasr.app

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.autoasr.app.databinding.ActivitySettingsBinding

class SettingsActivity : AppCompatActivity() {
    private lateinit var binding: ActivitySettingsBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.serverUrl.setText(ServerPrefs.getUrl(this))
        binding.saveButton.setOnClickListener {
            val url = binding.serverUrl.text?.toString().orEmpty().trim()
            if (!url.startsWith("https://")) {
                Toast.makeText(
                    this,
                    "Use an https:// URL so the microphone can start.",
                    Toast.LENGTH_LONG,
                ).show()
                return@setOnClickListener
            }
            ServerPrefs.setUrl(this, url)
            Toast.makeText(this, "Saved", Toast.LENGTH_SHORT).show()
            finish()
        }
    }
}
