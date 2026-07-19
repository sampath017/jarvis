package com.jarvis.edge.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.migration.Migration
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(entities = [OutboxEntity::class], version = 3, exportSchema = false)
abstract class OutboxDatabase : RoomDatabase() {

    abstract fun outboxDao(): OutboxDao

    companion object {
        @Volatile
        private var INSTANCE: OutboxDatabase? = null

        fun getDatabase(context: Context): OutboxDatabase {
            return INSTANCE ?: synchronized(this) {
                val instance = Room.databaseBuilder(
                    context.applicationContext,
                    OutboxDatabase::class.java,
                    "jarvis_outbox_db"
                )
                    .addMigrations(MIGRATION_1_2, MIGRATION_2_3)
                    .build()
                INSTANCE = instance
                instance
            }
        }

        private val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL(
                    "ALTER TABLE outbox_events ADD COLUMN motionRms REAL"
                )
            }
        }

        private val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL(
                    "ALTER TABLE outbox_events ADD COLUMN gyroRms REAL"
                )
            }
        }
    }
}
