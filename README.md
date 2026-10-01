# IMOTION banking corpus

Public app reviews and banking discussions collected for the IMOTION project. This snapshot contains 1,012,141 review, post and comment records, plus 486,393 developer replies in separate files. It covers nine Google Play apps, two X search exports, 320 attempted YouTube sources and 19 attempted Reddit pages.

## Contents

| Table | Input records | Retained | Removed |
| --- | ---: | ---: | ---: |
| Google Play reviews | 935,950 | 929,596 | 6,354 |
| X posts and replies | 32,198 | 32,198 | 0 |
| YouTube comments and replies | 50,128 | 49,954 | 174 |
| Reddit posts and comments | 393 | 393 | 0 |
| Main corpus | 1,018,669 | 1,012,141 | 6,528 |
| Google Play developer replies | 486,402 | 486,393 | 9 |

The 21 data CSVs total 421,740,659 bytes. Every file is under 90 MB. Google Play has one folder per app, each containing `reviews.csv` and `developer_replies.csv`. X, YouTube and Reddit each have one text table. Metadata separately preserves 660 captured X quote-context versions and one Reddit image caption. These 661 context records do not increase the main corpus count.

## Repository layout

| Path | Contents |
| --- | --- |
| `data/google_play/<app>/reviews.csv` | Review text, rating, dates, version and source reference |
| `data/google_play/<app>/developer_replies.csv` | Developer responses linked by review and source ID |
| `data/x/posts.csv` | X posts and replies |
| `data/youtube/comments.csv` | YouTube comments and replies |
| `data/reddit/posts_comments.csv` | Visible Reddit posts and comments |
| `metadata/` | Source manifests, context, input checksums and planned X queries |
| `methodology/` | Collection and cleaning methods |
| `reports/` | Counts, removal ledgers, file checksums and validation results |
| `scripts/` | Local cleaning and packaging code |
| `scripts/collection/` | Supplied review collector and Windows launcher |

## Working with the data

CSV files use UTF-8 and standard quoting. Read IDs as strings and use a CSV parser because text can contain line breaks. Each row retains its position in the corresponding input file through `source_row`. `source_id` links rows to the platform's source manifest. The data dictionary describes each field and date convention.

Developer replies are separate from customer reviews. Their `parent_review_retained` field marks whether the customer review remains in the text corpus. There are 2,205 retained responses to reviews excluded by the text rules.

Cleaning removes blank, symbol-only and explicit deleted-placeholder text. It preserves short responses, spelling, slang, mixed languages, numeric-only responses and repeated wording under different IDs. It removes author/profile columns, media and derived sentiment/topic fields. Source URLs and mentions within text remain. The cleaning method gives the exact rules and removal reasons.

The Google Play snapshot records collection on 19 September 2026. X publication dates cover October 2024 through September 2026. YouTube and Reddit collection took place on 1 October 2026. YouTube dates are estimates; Reddit relative-age labels do not establish exact publication dates. Each collection method documents source selection and coverage.

## Rebuilding this snapshot

Place the original Google Play CSV, both X JSON exports and `IMOTION_AgentReach_Raw_2026-10-01.zip` outside this repository. `metadata/input_files.csv` identifies them by filename and checksum. The cleaned data does not duplicate the original large exports.

Python 3.10 or later can run the cleaning scripts using only its standard library:

```bash
python scripts/prepare_dataset.py \
  --reviews ../inputs/IMOTION_cleaned_reviews_935950.csv \
  --x ../inputs/dataset_x-tweet-scraper_2026-10-01_07-39-17-883.json \
  --x ../inputs/dataset_x-tweet-scraper_2026-10-01_07-51-26-594.json \
  --agentreach ../inputs/IMOTION_AgentReach_Raw_2026-10-01.zip \
  --output ../imotion-corpus-rebuilt
```

Use a new or empty output directory. This command processes local files and makes no network requests. The supplied collection scripts are historical collection references; rebuilding this snapshot does not run them. The counts and collection scope above describe these exact inputs.

## GitHub Desktop

Extract the delivery archive and create a local repository for the `imotion-corpus` folder in GitHub Desktop. Commit the extracted files, then publish the repository as public. Keep the ZIP and original input exports outside the repository; `.gitignore` excludes them. `.gitattributes` preserves CSV bytes across platforms so checksums remain stable.
