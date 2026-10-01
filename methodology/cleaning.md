# Cleaning and packaging

The repository starts from the supplied Google Play CSV, two X JSON exports and the earlier YouTube/Reddit archive. Source hashes and filenames appear in `metadata/input_files.csv`. The process does not fetch new records.

## Text rules

Text changes consist of removing null characters and trimming whitespace at the beginning and end. Internal spacing, line breaks, spelling, case, slang, punctuation, links and emojis within written text remain intact.

The text check removes three kinds of records:

| Reason | Rule |
| --- | --- |
| `empty_text` | No text remains after trimming. |
| `symbol_only` | No Unicode letter or number remains in a temporary classification copy after removing keycap emoji sequences. This also catches punctuation-only entries and common symbol-only emoticons. |
| `deleted_placeholder` | The complete trimmed text equals `[deleted]` or `[removed]`, ignoring case. |

The classification copy never replaces the stored text. Numeric-only responses remain. Short entries such as `ok` and `wkwk` remain. A letter-bearing emoticon such as `:D` remains under this conservative rule. Google Play checks the title and body together, so a written title can preserve a review with an empty body. Developer replies use the same text rules independently.

## Duplicates and relationships

Records with different source IDs remain even when their wording matches. Google Play compares the app and review ID with the review date, rating, title and body; a repeated matching capture is removed, while a changed review is retained. Developer responses use the review ID, response text and response date. Social records compare their supplied IDs and complete original payloads; differing payload versions remain traceable. This pass found no duplicate captures in the main input tables.

Developer replies occupy separate files and do not increase the customer-review count. A reply can remain when its parent review fails the text check. `parent_review_retained=false` marks that case, and the removal ledger identifies the excluded review. Blank reply-parent IDs stay blank. Conversation IDs do not fill missing parent IDs.

Quoted X posts and the Reddit image caption remain in metadata as context. They do not increase the main corpus count. Quote-context versions preserve differences in their original captured payloads, including changes outside the reduced context columns.

## Columns and dates

The tables retain text, native or supplied record IDs, source references, dates, relationships and selected rating/engagement fields. Source manifests hold repeated app, video and thread metadata. The process drops profile names, author IDs, handles, avatars, biographies, media objects, redundant URL aliases and derived sentiment/topic fields. Source URLs and mentions within the text remain, so removing author columns does not make the dataset anonymous.

Google Play and X retain their supplied publication dates. YouTube estimates remain explicitly marked as estimates, with the original relative-age label and uncertainty fields. Reddit retains relative-age labels and leaves exact dates blank. No date, language, rating, app, sentiment or topic filter applies during this pass.

## Files and checks

Each app has a review file and a developer-response file. X, YouTube and Reddit each have a separate text table. The writer splits a table only if its next complete CSV record would exceed 90,000,000 bytes. There is no row-count ceiling. It counts UTF-8 bytes after CSV quoting and includes the header. Every current table fits in one file.

All CSVs use UTF-8, comma delimiters, a header row and standard quoting. Empty cells represent empty values. IDs must remain strings. CSV records can contain quoted line breaks, so physical line counts are not row counts. Spreadsheet imports should treat IDs and text columns as text.

The removal ledgers record IDs, input positions and reasons. Summary tables reconcile input, retained and removed counts. File checksums and record counts appear in `reports/file_manifest.csv`. Source-to-output checks compare retained wording with the supplied text after only the stated trim/null-character operation.
