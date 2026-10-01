# Reddit discussions

The incoming forum export contains 393 written utterances from 13 public r/finansial threads: 12 opening posts and 381 comments. A separate file contains one image-renderer alt-text record from an opening post. That caption is source context and is excluded from the written-utterance count. The collection date was 1 October 2026.

Discovery used public bank-choice searches and related discussion URLs found on retrieved pages. Search results supplied URLs only. A direct unauthenticated Reddit JSON request returned HTTP 403 and stopped. The web retrieval service then opened ordinary public thread pages. The recorded method is `web_tool_direct_public_page_open`; Agent Reach did not collect these rows. There were 19 attempted discussion entries, including six that supplied no usable thread body.

Each row represents one visible written post or comment. The extraction removed page navigation, author-header controls, badges, share controls, unrelated recommendations and footers. It normalized renderer link notation and whitespace while preserving wording, spelling, slang, punctuation and paragraph order. It covered visible replies only. The image caption came from the page renderer; the workflow did not run independent OCR.

Opening posts retain native thread IDs. Comment IDs beginning `rendered_` are synthetic identifiers built from the source URL, retrieval line and text hash. Retrieval references and line locators support tracing these rows. The render did not expose native comment-parent IDs, so parent fields remain blank; a thread URL does not establish that a comment directly answered the opening post.

Relative age labels remain as text. Absolute publication dates stay blank because the renders can be cached and do not establish reliable calendar dates. Retrieval-envelope timestamps cover 370 utterances; 23 rows from the initial batch have blank collection timestamps. Export time is a separate field.

The original forum extraction removed three exact within-source text duplicates. Contact-detail scans reported zero affected utterance rows. No MediaKonsumen or Kaskus text entered this collection. The visible, selected discussions provide contextual public statements rather than a complete thread archive or a representative customer sample.
