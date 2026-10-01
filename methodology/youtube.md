# YouTube comments

The original collection took place on 1 October 2026. The final archive records a cutoff of 06:54:09 UTC. It attempted 320 selected videos and retrieved comments from 256. The incoming archive contains 50,128 native comment records: 28,080 top-level comments and 22,048 replies. One reply has blank text, leaving 50,127 records containing text. Collector statuses are 317 returned, two capped and one partial timeout. A returned job can contain zero comments and does not establish complete retrieval.

Setup used Agent Reach 1.5.0 in an isolated Python environment, and its doctor checked available routes. The collection code directly invoked its installed yt-dlp dependency, version 2026.8.19, with an orchestration and checkpoint wrapper. Agent Reach supplied setup; yt-dlp performed comment extraction. The collector downloaded no audio or video and used no account cookies or login credentials.

Initial web searches supplied seed URLs. Further discovery parsed ordinary public YouTube search pages with Indonesian language and Indonesia locale. Three non-overlapping manifests selected 194, 98 and 28 videos. Selection used source-level relevance and observed views. Queries covered Aladin, competitors, bank comparisons, QRIS, switching, payroll and household banking. The reserve added banking incidents, service explainers, fees and bank-choice discussions. These source groups remain distinct from labels assigned to individual comments.

Retrieval used newest-first ordering, a combined cap of 3,000 comments and replies per video, a 15-second socket timeout, one request retry, one extractor retry and a 240-second process limit. At most five video jobs ran concurrently. Replies and pinned comments can appear outside strict date order. Completed extraction output took precedence; checkpoints supplied recovered partial records. The exporter selected one version per source instead of concatenating both.

The exporter preserved comment text, native parent IDs and YouTube relative-age labels alongside yt-dlp's estimated timestamps. Flags against 1 October 2024 through 30 September 2026 in Asia/Jakarta did not remove rows or establish exact publication dates. The archive retains older and newer comments. The final extractor `comment_count` is the returned list length; the initial count hint supplies an approximate traversal diagnostic.

Search selection, caps, moderation, deleted comments and hidden replies constrain coverage. These records are public statements, not verified customers or a representative sample of banking users.
