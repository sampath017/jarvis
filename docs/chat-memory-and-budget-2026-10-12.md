> Historical release notes. The Android-only local storage migration supersedes the storage and deployment details below; see [current storage](android-local-storage.md).

# Conversation recall, file-context performance, and daily allowance

The daily AI allowance is Rs 50, reset at midnight Asia/Kolkata. Existing usage and in-flight reservations remain in the same Firestore ledger. Health metadata, rejection messages, and startup logging use the same configured amount. See `ai-budgets.md` for conversion and billing scope.

## Conversation memory

- Short term: up to 24 recent messages, bounded to 16,000 characters on both the phone and backend. Errors and internal attachment notices are excluded.
- Long term: retrieve question/answer pairs from existing saved chats on the phone, including synced older chats. Retrieve at most 80 candidate questions, rank relevant answers, and send at most five within 12,000 characters.
- Recall is lexical, with Aadhaar spelling aliases and Unicode word support. This is retrieval of historical answers, not a new verified personal-fact database or a rolling summary.
- Preserve source chat, message IDs, and answer timestamp. Prefer newer equivalent answers; exclude answers immediately challenged by the user, failed replies, and replies that executed actions. Avoid duplicating answers already present in recent context.
- Current-time and explicit refresh questions bypass long-term recall. New attachments take precedence. Agent instructions require preserving person/source attribution and verifying conflicting or ambiguous evidence.
- Deleting a saved chat removes its recall source. Personal identifiers are not copied into an additional permanent store. Recall does not independently recheck the current Drive file version; ask to recheck when fresh verification is needed.

## Other fixes and measurements

- Score each cached file once, instead of tokenizing its caption repeatedly during sorting. Precompile Unicode token expressions, support short filenames such as PAN/CV, and use an explicit recent-cache-order tiebreaker.
- Preserve the original request ID through stream recovery even if the caller mutates its payload.
- Add a SQLite expression index on thread and parsed timestamp to support mixed UTC/offset history correctly and efficiently.
- Synthetic local file-selection benchmark, 5,000 files with 150-word captions, median of five warmed runs: 2,262,626 microseconds before, 674,111 after (3.36x faster).
- Synthetic local SQLite benchmark, 10,000 messages and 80 candidates: 1,112.4 ms with the ordinary timestamp index, 13.8 ms with the parsed-timestamp index. These are development-machine measurements, not phone or end-to-end model latency guarantees.

## Verification

- Expanded backend regression suite: 101 passed, covering file references/readers, indexing, streaming recovery, real SQLite memory queries, recall prompts, and transactional spending enforcement.
- Full mobile suite before conversation-memory integration: 95 passed. A subsequent focused integration run passed 50 tests; final memory/correction and chat-ordering run passed 19 tests, including all 15 new memory cases.
- Static analysis of changed mobile files: no issues.
- Live backend revision: `jarvis-backend-00120-jab`, 100% traffic. Candidate and public health checks confirm `daily_budget_inr: 50`; candidate schema accepts recalled answers and retains the Google file URL fix.
- Synthetic live model smoke test: returned the remembered reference code with no tool requests.
- Release APK built and installed successfully on the connected phone. Startup process verified; filtered startup logs showed no fatal or SQLite errors.

No Git commits were made.
