# X posts collected through Apify

The two incoming JSON exports contain 32,198 dataset records from the X Tweet Scraper workflow using `xquik/x-tweet-scraper`. Both filenames carry the date 1 October 2026. Post publication times come from each record's `createdAt`, not the export filename.

| Source file ending | Records | Earliest post, UTC | Latest post, UTC |
| --- | ---: | --- | --- |
| `07-39-17-883.json` | 13,370 | 2025-10-01 00:59:46 | 2026-09-30 23:47:50 |
| `07-51-26-594.json` | 18,828 | 2024-10-01 00:27:45 | 2025-09-30 23:24:33 |

Each export records the same 23 search terms. They cover named banks, support-account replies and mentions, bank choice, switching, fees, syariah banking and payment problems. Aladin searches use brand phrases; support-handle searches cover Jago, BSI, SeaBank, blu and Jenius. Search terms identify the retrieval query. They do not establish a bank association or experience category for every post.

The saved collection configurations specify search mode, Indonesian language, Latest ordering, retweet exclusion, 32,666 maximum items per run and 5,000 per target. They divide the search into two annual windows beginning 1 October 2024 and 1 October 2025. These configuration files document the planned collection. The exports provide the observed records, search terms, dates and flags. All exported records carry `lang=in` and `isRetweet=false`; the type fields contain 24,357 replies and 7,841 tweets.

The exports include post IDs, URLs, conversation IDs, engagement counts and nested author, quote and long-post objects. A nested quoted post supplies context for the enclosing record. The corpus count excludes these context records. `noteTweet.text` can contain a longer text version than the top-level text. Conversation IDs identify threads. They do not identify immediate reply parents.

This is a purposive search collection. Ranking, query wording, language tagging, target limits and platform visibility affect which posts appear. A matching reply does not establish full conversation coverage. Engagement counts describe the exported snapshot, and account metadata does not verify customer identity or personal characteristics.
