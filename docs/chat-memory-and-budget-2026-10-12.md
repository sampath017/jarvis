# Conversation history, recalled answers and allowance

This guide describes current behavior; the filename is retained for existing links.

## Current-chat history

`ChatStorageService.loadCommandHistory()` reads the complete selected thread from
SQLite independently of visible scroll pagination, merges unsaved in-memory
messages by ID, and preserves ordering. It excludes the current user message,
which is sent separately as the command text. An incomplete read fails visibly
instead of sending a shortened conversation.

`ConversationMemory.fullHistory()` validates roles, content and timestamps. It
preserves earlier turns and marks application errors as unverified answers. The
Python normalizer follows the same full-history rule. There is no rolling summary,
24-turn cutoff or silent character-based compaction of the selected chat.

The agent numbers prior user/assistant turns and includes UTC/Asia-Kolkata sent
times when known. If the complete conversation exceeds the configured model's
context window, the command stops with a clear new-chat instruction; the complete
conversation remains saved on the phone.

## Separately recalled answers

Optional recall searches saved question/answer pairs on the phone. It ranks
lexical overlap, supports spelling aliases and Unicode, retains source thread and
message IDs, and sends at most five answers within 12,000 characters. It excludes
failed/action-executing answers, immediately challenged replies and answers already
present in the current conversation. Explicit fresh/current-information requests
and new attachments can bypass recall.

Recall is historical evidence, not an independently verified fact store. Source
attribution and timestamps matter; changed files or ambiguous answers require
verification with the appropriate tool. Deleting a saved chat removes that recall
source.

## Costs and verification

Full dialogue increases input as a chat grows. Per-call reservations and the daily
USD allowance still apply; see [AI budgets](ai-budgets.md). The model invocation is
fresh for each command; permanent history remains in Android SQLite.

Relevant regressions include `tests/android/ui/conversation_memory_test.dart`,
`tests/android/ui/chat_query_cost_test.dart`, `tests/backend/test_conversation_memory.py`
and `tests/backend/test_complete_reply.py`. Scripted-provider tests verify the
history contract, not live model accuracy or provider billing.
