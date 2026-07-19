package com.jarvis.edge.data.local

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface OutboxDao {

    @Query("SELECT * FROM outbox_events ORDER BY occurredAt ASC")
    suspend fun getAllEvents(): List<OutboxEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertEvent(event: OutboxEntity)

    @Query("DELETE FROM outbox_events WHERE eventId = :eventId")
    suspend fun deleteEventById(eventId: String)

    @Query("DELETE FROM outbox_events WHERE eventId IN (:eventIds)")
    suspend fun deleteEventsByIds(eventIds: List<String>)

    @Query("SELECT COUNT(*) FROM outbox_events")
    suspend fun getCount(): Int
}
