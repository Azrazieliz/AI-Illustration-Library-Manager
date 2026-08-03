package com.ailm.android.startup

import android.app.Application

class AilmApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        AppBootstrap.initializeApplication(applicationContext)
    }
}
