# Data dictionary

IDs are strings. Empty cells represent empty values. Counts describe the captured source snapshot and are not estimates of total discussion volume. CSV row positions start at one after the header; X positions start at one in the original JSON array.

## Google Play reviews

| Field | Definition |
| --- | --- |
| `review_id` | Supplied Google Play review ID |
| `app_name` | App name in the input export |
| `source_id` | Join key for `metadata/google_play_sources.csv` |
| `review_date` | Supplied review publication/update timestamp |
| `rating` | Supplied star rating |
| `review_title` | Supplied review title, with outer whitespace trimmed |
| `review_text` | Supplied review body, with outer whitespace trimmed |
| `app_version` | App version reported for the review |
| `helpful_count` | Supplied `thumbs_up_count` value |
| `fetch_locale` | Collector's language/country locale |
| `collected_at` | Supplied `fetched_at` timestamp |
| `source_row` | Data-record position in the incoming combined CSV |

The source manifest holds the app ID, store URL, original source filename and observed collection times/locales. `review_title` and `review_text` remain separate. The text check considers both.

## Google Play developer replies

| Field | Definition |
| --- | --- |
| `review_id` | Parent review ID |
| `app_name` | App associated with the response |
| `source_id` | Same app-source join key as the review table |
| `reply_text` | Supplied developer response, with outer whitespace trimmed |
| `reply_date` | Supplied developer response timestamp |
| `parent_review_retained` | `true` if that source row's review remains; otherwise `false` |
| `source_row` | Position of the parent record in the incoming combined CSV |

Use `source_id` and `review_id` together when linking reviews and responses. A response can remain after the text check excludes its parent. The removal ledger preserves that parent's ID and input position.

## Social text tables

| Field | Definition |
| --- | --- |
| `record_id` | Native X/YouTube ID or supplied Reddit record ID |
| `record_version` | Capture version within a repeated ID; currently one throughout the main tables |
| `source_id` | Join key for the platform's source manifest |
| `record_type` | Source record type, such as tweet, reply, comment or opening post |
| `text` | Supplied written text after outer trimming and null-character removal |
| `record_url` | Source permalink or supplied thread-level URL |
| `parent_id` | Immediate source parent ID when the export contains one |
| `source_row` | Original array/data-record position; the source manifest identifies the input |
| `duplicate_id_flag` | Marker for differing captures under one source ID; empty in the current main tables |
| `like_count` | Captured like count, where supplied |

### X-specific fields

| Field | Definition |
| --- | --- |
| `published_at` | Parsed source publication timestamp in UTC |
| `conversation_id` | Native conversation root ID; distinct from an immediate parent |
| `quoted_post_id` | Native quoted-post ID, where present |
| `language` | Source language code; the supplied X exports use `in` |
| `reply_count` | Captured reply count |
| `view_count` | Captured view count |
| `search_term` | Exported retrieval query associated with the record |
| `timestamp_basis` | Provenance of the publication timestamp |

`metadata/x_quote_context.csv` holds quoted-post IDs, capture versions, text, publication dates, URLs and version flags. These records are context. They are not extra retrieved posts in the main count. Captured versions can differ in source fields omitted from this reduced context table.

### YouTube-specific fields

| Field | Definition |
| --- | --- |
| `published_at_estimated` | yt-dlp's estimated publication timestamp |
| `published_at_text` | Original relative-age label |
| `time_precision` | Source timestamp precision label |
| `time_uncertainty` | Recorded uncertainty in the estimate |
| `time_window_flag` | Original approximate flag against the October 2024 to September 2026 reference window |
| `collected_at` | Recorded collection timestamp |
| `collected_at_basis` | How the collection timestamp was established |

No time-window flag causes a row to be removed. `metadata/youtube_sources.csv` preserves all 320 attempts, including zero-comment sources, caps, partial completion, source selection and extraction settings. Its query and context categories describe video selection, not comment-level labels.

### Reddit-specific fields

| Field | Definition |
| --- | --- |
| `record_id_type` | Distinguishes native thread IDs from synthetic rendered-comment IDs |
| `published_at` | Exact date field; empty for this rendered-page collection |
| `published_at_text` | Relative-age label from the rendered source |
| `collected_at` | Retrieval-envelope timestamp, where recorded |
| `collected_at_basis` | Provenance of that retrieval timestamp |
| `source_locator` | Retrieval reference and line locator |
| `text_scope` | Extent of text exposed by the rendered source |

`metadata/reddit_sources.csv` records all 19 attempted pages. `metadata/context.csv` holds the single renderer-supplied image caption and its source reference.

## Reports

`reports/cleaning_summary.csv` reconciles input, retained and removed records by table. `google_play_by_app.csv` gives the same operational counts by app. Removal ledgers contain record identifiers, source positions and reasons, without duplicating excluded text. Zero denotes no recorded event; empty values do not imply zero in the corpus tables.

`reports/file_manifest.csv` records each delivered file's relative path, byte size and SHA-256 checksum, with parsed record counts for CSVs. The manifest excludes itself. Stage JSON reports retain counts, source hashes and text-preservation checks.
