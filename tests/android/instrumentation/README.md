# Native database-open regression

This separate instrumentation suite exercises the actual Android SQLite API. JVM
Android stubs and Python SQLite cannot detect Android's `execSQL` rejection of a
row-returning `PRAGMA` assignment. No additional test library is required.

Every database request is redirected to a unique disposable file in the target
app's cache. The suite never opens, replaces or clears the user's database,
preferences, reminders or queue. Seven checks cover receipt reads across reopens,
committed WAL context reads, safe handling of a missing database, rejection of
unsupported agent state before a receipt can commit, historical event evidence,
transaction rollback before acknowledgement, and raw quarantine of malformed
timestamps without inventing timeline entries. History archival preserves current
reminders, journeys, budgets and notification state and deduplicates receipts.

Compile from `mobile/android/` using the configured JDK:

```powershell
./gradlew.bat :app:assembleDebugAndroidTest
```

With an authorized matching debug app and test APK installed on a test device or
emulator:

```powershell
adb shell am instrument -w com.jarvis.jarvis_collector.test/com.jarvis.jarvis_collector.MobileRecordsOpenInstrumentation
```

Expect `OK (7 tests)`. Add `-e mode open` for the four database-open and protocol
checks or `-e mode archive` for the three historical archival checks.

The ordinary `tests/run.py --suite android` runs JVM policy tests; it does not run
this device-only suite. Compiling the test APK does not establish that the actual
Android SQLite regression has passed.
