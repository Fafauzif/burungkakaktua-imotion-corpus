"""Build lean social tables from supplied exports, without online collection."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from corpus_common import ShardWriter, classify_text, trim_text, emit_csv, write_json


X_COLUMNS = [
    'record_id', 'record_version', 'source_id', 'record_type', 'text',
    'published_at', 'record_url', 'parent_id', 'conversation_id', 'quoted_post_id',
    'language', 'like_count', 'reply_count', 'view_count', 'search_term',
    'source_row', 'timestamp_basis', 'duplicate_id_flag',
]
YOUTUBE_COLUMNS = [
    'record_id', 'record_version', 'source_id', 'record_type', 'text',
    'record_url', 'parent_id', 'like_count', 'published_at_estimated',
    'published_at_text', 'time_precision', 'time_uncertainty', 'time_window_flag',
    'collected_at', 'collected_at_basis', 'source_row', 'duplicate_id_flag',
]
REDDIT_COLUMNS = [
    'record_id', 'record_version', 'source_id', 'record_id_type', 'record_type',
    'text', 'record_url', 'parent_id', 'published_at', 'published_at_text',
    'collected_at', 'collected_at_basis', 'source_locator', 'text_scope',
    'source_row', 'duplicate_id_flag',
]
REMOVED_COLUMNS = ['platform', 'source_id', 'source_file', 'source_member',
                   'source_row', 'record_id', 'reason']
CONTEXT_COLUMNS = ['source_id', 'record_id', 'record_type', 'title', 'text',
                   'source_url', 'published_at_text', 'collected_at',
                   'collected_at_basis', 'text_scope', 'source_locator', 'source_row']


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def digest_payload(row):
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def text_digest(rows):
    h = hashlib.sha256()
    for row in rows:
        data = row['text'].encode('utf-8')
        h.update(len(data).to_bytes(8, 'big'))
        h.update(data)
    return h.hexdigest()


def zip_rows(archive, member):
    with archive.open(member) as stream:
        yield from csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig', newline=''))


def reddit_source_id(url):
    found = re.search(r'/comments/([^/]+)', url or '')
    return 'reddit:' + found.group(1) if found else 'reddit:url:' + hashlib.sha256((url or '').encode()).hexdigest()[:16]


class Accumulator:
    """Classify rows, deduplicate exact original payloads and retain differing versions."""

    def __init__(self, platform, removed):
        self.platform = platform
        self.removed = removed
        self.rows = []
        self.seen = defaultdict(dict)
        self.raw_ids = Counter()
        self.raw_count = 0
        self.reasons = Counter()
        self.source_raw = Counter()
        self.source_kept = Counter()
        self.source_removed = Counter()
        self.trimmed_count = 0
        self.nul_count = 0
        self.expected_text = []

    def add(self, original, clean, source_file, source_member='', text_value=None):
        self.raw_count += 1
        source_id = clean['source_id']
        self.source_raw[source_id] += 1
        record_id = clean.get('record_id') or ''
        if record_id:
            self.raw_ids[record_id] += 1
        raw_text = text_value if isinstance(text_value, str) else ''
        clean['text'] = trim_text(text_value)
        if clean['text'] != raw_text:
            self.trimmed_count += 1
        if '\x00' in raw_text:
            self.nul_count += 1
        reason = classify_text(clean['text'])
        if not reason:
            payload_hash = digest_payload(original)
            # No deduplication by text or across different native/supplied IDs.
            identity = record_id or (source_id, clean['source_row'])
            if payload_hash in self.seen[identity]:
                reason = 'duplicate_identical_payload'
        if reason:
            self.reasons[reason] += 1
            self.source_removed[source_id] += 1
            self.removed.append(dict(platform=self.platform, source_id=source_id,
                                     source_file=source_file, source_member=source_member,
                                     source_row=clean['source_row'], record_id=record_id,
                                     reason=reason))
            return
        clean['record_version'] = len(self.seen[identity]) + 1
        clean['duplicate_id_flag'] = 'false'
        self.seen[identity][payload_hash] = len(self.rows)
        self.rows.append(clean)
        self.expected_text.append(trim_text(text_value))
        self.source_kept[source_id] += 1

    def finish(self, repo, relative_dir, columns, basename):
        differing_ids = 0
        for versions in self.seen.values():
            if len(versions) > 1:
                differing_ids += 1
                for index in versions.values():
                    self.rows[index]['duplicate_id_flag'] = 'true'
        assert len(self.rows) + sum(self.reasons.values()) == self.raw_count
        assert all(row['text'] == expected for row, expected in zip(self.rows, self.expected_text))
        writer = ShardWriter(repo, relative_dir, columns, basename=basename)
        for row in self.rows:
            writer.write(row)
        files = writer.close()
        expected_hash = text_digest(self.rows)
        exported_rows = []
        for item in files:
            path = Path(item['path'])
            if not path.is_absolute():
                path = Path(repo) / path
            with path.open(encoding='utf-8-sig', newline='') as stream:
                exported_rows.extend(csv.DictReader(stream))
        assert len(exported_rows) == len(self.rows)
        assert text_digest(exported_rows) == expected_hash
        assert all(row['text'] == expected for row, expected in zip(exported_rows, self.expected_text))
        return {
            'raw_rows': self.raw_count, 'retained_rows': len(self.rows),
            'removed_rows': sum(self.reasons.values()), 'removal_reasons': dict(self.reasons),
            'raw_unique_nonempty_source_ids': len(self.raw_ids),
            'raw_duplicate_id_excess_rows': sum(n - 1 for n in self.raw_ids.values()),
            'different_payload_id_groups_retained': differing_ids,
            'trim_or_nul_changed_rows': self.trimmed_count, 'nul_containing_rows': self.nul_count,
            'columns': columns, 'files': files,
            'retained_text_sha256_length_prefixed': expected_hash,
            'source_to_output_text_preservation_verified': True,
            'row_reconciliation_verified': True,
        }


def build_social(repo, input_paths, agent_zip):
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=True)
    removed = []
    input_manifests = []
    x = Accumulator('x', removed)
    x_sources = []
    quote_rows, quote_versions = [], defaultdict(dict)
    quote_input_count = 0
    note_counts = Counter()
    for input_path in input_paths:
        path = Path(input_path)
        file_hash = digest_file(path)
        source_id = 'x:' + file_hash[:16]
        input_manifests.append({'source_file': path.name, 'bytes': path.stat().st_size,
                                'sha256': file_hash, 'source_id': source_id, 'platform': 'x'})
        with path.open(encoding='utf-8-sig') as stream:
            records = json.load(stream)
        if not isinstance(records, list):
            raise ValueError(f'Expected JSON array: {path.name}')
        dates, terms, languages = [], Counter(), Counter()
        for number, row in enumerate(records, 1):
            if not isinstance(row, dict):
                raise ValueError(f'Expected object: {path.name}, row {number}')
            record_type = row.get('type') or row.get('resultType') or ''
            if record_type not in ('tweet', 'reply'):
                raise ValueError(f'Unexpected X row type: {record_type!r}')
            terms[row.get('searchTerm') or ''] += 1
            languages[row.get('lang') or ''] += 1
            if row.get('createdAt'):
                dates.append(row['createdAt'])
            note = row.get('noteTweet')
            if isinstance(note, dict) and isinstance(note.get('text'), str):
                note_counts['present'] += 1
                if note['text'] == row.get('text'):
                    note_counts['equal_to_top_level_text'] += 1
                else:
                    # No different note text occurs in the supplied files. Stop for review
                    # if a future input requires a full-text selection decision.
                    raise ValueError('Different noteTweet.text requires source text selection review')
            quote = row.get('quoted_tweet')
            if isinstance(quote, dict) and quote.get('id'):
                quote_input_count += 1
                if str(quote['id']) != str(row.get('quotedTweetId')):
                    raise ValueError('Quoted post ID does not match its source reference')
                qid, qhash = str(quote['id']), digest_payload(quote)
                if qhash not in quote_versions[qid]:
                    quote_versions[qid][qhash] = len(quote_rows)
                    quote_rows.append({
                        'quoted_post_id': qid, 'record_version': len(quote_versions[qid]),
                        'text': trim_text(quote.get('text')),
                        'published_at': quote.get('createdAt') or '',
                        'record_url': quote.get('url') or '', 'duplicate_id_flag': 'false',
                    })
            clean = {
                'record_id': row.get('id') or '', 'source_id': source_id,
                'record_type': record_type, 'published_at': row.get('createdAt') or '',
                'record_url': row.get('url') or row.get('tweetUrl') or '',
                'parent_id': row.get('inReplyToId') or '',
                'conversation_id': row.get('conversationId') or '',
                'quoted_post_id': row.get('quotedTweetId') or '',
                'language': row.get('lang') or '', 'like_count': row.get('likeCount'),
                'reply_count': row.get('replyCount'), 'view_count': row.get('viewCount'),
                'search_term': row.get('searchTerm') or '', 'source_row': number,
                'timestamp_basis': 'source_createdAt_string',
            }
            x.add(row, clean, path.name, text_value=row.get('text'))
        x_sources.append({
            'source_id': source_id, 'input_file': path.name, 'input_sha256': file_hash,
            'raw_rows': len(records), 'retained_rows': x.source_kept[source_id],
            'removed_rows': x.source_removed[source_id],
            'observed_search_term_count': len(terms),
            'observed_language_codes': json.dumps(sorted(languages), ensure_ascii=False),
            'source_method': 'supplied_x_tweet_scraper_json_export',
            'actor_id_evidence': 'not_embedded_in_export',
            'run_id': '', 'collected_at': '',
            'settings_evidence': 'searchTerm_and_result_fields_only;actual_input_not_embedded',
            'date_basis': 'createdAt_is_post_publication_not_collection_time',
        })
        del records
    x_summary = x.finish(repo, 'data/x', X_COLUMNS, 'posts')
    x_summary['missing_parent_id_reply_rows_retained'] = sum(
        r['record_type'] == 'reply' and not r['parent_id'] for r in x.rows)
    x_summary['note_tweet_text_checks'] = dict(note_counts)
    x_summary['full_text_selected_rows'] = 0
    for versions in quote_versions.values():
        if len(versions) > 1:
            for index in versions.values():
                quote_rows[index]['duplicate_id_flag'] = 'true'
    quote_columns = ['quoted_post_id', 'record_version', 'text', 'published_at',
                     'record_url', 'duplicate_id_flag']
    emit_csv(repo / 'metadata/x_quote_context.csv', quote_columns, quote_rows)
    with (repo / 'metadata/x_quote_context.csv').open(encoding='utf-8', newline='') as stream:
        serialized_quotes = list(csv.DictReader(stream))
    assert text_digest(serialized_quotes) == text_digest(quote_rows)
    x_summary['quote_context'] = {
        'raw_direct_quote_objects': quote_input_count, 'retained_context_versions': len(quote_rows),
        'unique_quoted_post_ids': len(quote_versions),
        'identical_payload_duplicates_collapsed': quote_input_count - len(quote_rows),
        'different_payload_id_groups_retained': sum(len(v) > 1 for v in quote_versions.values()),
        'context_rows_excluded_from_corpus': len(quote_rows),
        'text_preservation_verified': True,
        'scope': 'direct_quoted_tweet_objects_only;not_recursively_expanded',
    }
    emit_csv(repo / 'metadata/x_sources.csv', list(x_sources[0]) if x_sources else [], x_sources)

    youtube = Accumulator('youtube', removed)
    reddit = Accumulator('reddit', removed)
    agent_zip = Path(agent_zip)
    input_manifests.append({'source_file': agent_zip.name, 'bytes': agent_zip.stat().st_size,
                            'sha256': digest_file(agent_zip), 'platform': 'youtube;reddit'})
    with zipfile.ZipFile(agent_zip) as archive:
        candidates = [name for name in archive.namelist() if name.endswith('/raw_csv/youtube_comments_raw.csv')]
        if len(candidates) != 1:
            raise ValueError('Expected exactly one authoritative YouTube raw CSV in ZIP')
        yt_member = candidates[0]
        prefix = yt_member[:-len('raw_csv/youtube_comments_raw.csv')]
        video_records = list(zip_rows(archive, prefix + 'raw_csv/youtube_videos.csv'))
        statuses = {row['video_id']: row for row in zip_rows(archive, prefix + 'raw_csv/collection_status.csv')}
        for number, row in enumerate(zip_rows(archive, yt_member), 1):
            clean = {
                'record_id': row.get('comment_id') or '',
                'source_id': 'youtube:' + row['video_id'],
                'record_type': row.get('record_type') or '',
                'record_url': row.get('comment_url') or '', 'parent_id': row.get('parent_id') or '',
                'like_count': row.get('like_count'),
                'published_at_estimated': row.get('timestamp_estimated_utc') or '',
                'published_at_text': row.get('_time_text') or '',
                'time_precision': row.get('time_precision') or '',
                'time_uncertainty': row.get('time_uncertainty') or '',
                'time_window_flag': row.get('time_window_flag') or '',
                'collected_at': row.get('collected_at') or '',
                'collected_at_basis': row.get('collected_at_basis') or '',
                'source_row': number,
            }
            youtube.add(row, clean, agent_zip.name, yt_member, row.get('text_original'))
        youtube_summary = youtube.finish(repo, 'data/youtube', YOUTUBE_COLUMNS, 'comments')
        youtube_sources = []
        video_map = {row['video_id']: row for row in video_records}
        for vid in sorted(set(video_map) | set(statuses)):
            row, status = video_map.get(vid, {}), statuses.get(vid, {})
            source_id = 'youtube:' + vid
            youtube_sources.append({
                'source_id': source_id, 'video_id': vid,
                'source_url': row.get('video_url') or status.get('url') or '',
                'title': row.get('title') or status.get('title') or '',
                'upload_date': row.get('upload_date') or '',
                'query': row.get('query') or status.get('query') or '',
                'query_family': row.get('query_family') or status.get('query_family') or '',
                'selection_bucket': row.get('selection_bucket') or status.get('selection_bucket') or '',
                'context_bucket': row.get('context_bucket') or status.get('context_bucket') or '',
                'source_scope': row.get('source_scope') or status.get('source_scope') or '',
                'collection_status': status.get('status') or row.get('collection_status') or '',
                'collector': status.get('collector') or '',
                'collector_version': status.get('collector_version') or '',
                'comment_cap': status.get('comment_cap') or row.get('comment_cap') or '',
                'sort': status.get('sort') or row.get('sort') or '',
                'started_at': status.get('started_at') or row.get('started_at') or '',
                'finished_at': status.get('finished_at') or row.get('finished_at') or '',
                'source_record_count': youtube.source_raw[source_id],
                'retained_record_count': youtube.source_kept[source_id],
                'removed_record_count': youtube.source_removed[source_id],
                'upstream_comment_count': row.get('extractor_comment_count') or '',
                'cap_reached': row.get('cap_reached_by_observed_count') or '',
                'selected_source': row.get('selected_source') or status.get('selected_source') or '',
                'discovery_url': row.get('discovery_source_ref') or status.get('source_ref') or '',
                'error': status.get('error') or '',
                'input_file': agent_zip.name, 'input_member': yt_member,
            })
        emit_csv(repo / 'metadata/youtube_sources.csv', list(youtube_sources[0]), youtube_sources)
        youtube_summary['source_attempts'] = len(youtube_sources)
        youtube_summary['source_status_counts'] = dict(Counter(r['collection_status'] for r in youtube_sources))
        youtube_summary['sources_with_zero_exported_rows'] = sum(not r['source_record_count'] for r in youtube_sources)

        forum_member = prefix + 'raw_csv/forum_records.csv'
        forum_rows = list(zip_rows(archive, forum_member))
        source_titles = {}
        for number, row in enumerate(forum_rows, 1):
            source_id = reddit_source_id(row.get('source_url'))
            source_titles.setdefault(source_id, row.get('title') or '')
            clean = {
                'record_id': row.get('record_id') or '', 'source_id': source_id,
                'record_id_type': row.get('record_id_type') or '',
                'record_type': row.get('record_type') or '',
                'record_url': row.get('source_url') or '', 'parent_id': row.get('parent_id') or '',
                'published_at': row.get('published_at') or '',
                'published_at_text': row.get('published_at_text') or '',
                'collected_at': row.get('collected_at') or '',
                'collected_at_basis': row.get('collected_at_basis') or '',
                'source_locator': row.get('source_locator') or '',
                'text_scope': row.get('text_scope') or '', 'source_row': number,
            }
            reddit.add(row, clean, agent_zip.name, forum_member, row.get('text_original'))
        reddit_summary = reddit.finish(repo, 'data/reddit', REDDIT_COLUMNS, 'posts_comments')

        context_rows = []
        context_member = prefix + 'raw_csv/forum_context.csv'
        for number, row in enumerate(zip_rows(archive, context_member), 1):
            source_id = reddit_source_id(row.get('source_url'))
            source_titles.setdefault(source_id, row.get('title') or '')
            context_rows.append({
                'source_id': source_id, 'record_id': row.get('record_id') or '',
                'record_type': row.get('record_type') or '', 'title': row.get('title') or '',
                'text': trim_text(row.get('text_original')), 'source_url': row.get('source_url') or '',
                'published_at_text': row.get('published_at_text') or '',
                'collected_at': row.get('collected_at') or '',
                'collected_at_basis': row.get('collected_at_basis') or '',
                'text_scope': row.get('text_scope') or '',
                'source_locator': row.get('source_locator') or '', 'source_row': number,
            })
        emit_csv(repo / 'metadata/context.csv', CONTEXT_COLUMNS, context_rows)
        attempts = json.loads(archive.read(prefix + 'provenance/forum_retrieval_manifest.json'))
        reddit_sources = []
        for row in attempts:
            source_id = reddit_source_id(row.get('url'))
            reddit_sources.append({
                'source_id': source_id, 'source_url': row.get('url') or '',
                'title': source_titles.get(source_id, ''), 'collection_status': row.get('status') or '',
                'source_method': 'web_tool_direct_public_page_open',
                'source_ref': row.get('source_ref') or '',
                'source_record_count': reddit.source_raw[source_id],
                'retained_record_count': reddit.source_kept[source_id],
                'removed_record_count': reddit.source_removed[source_id],
                'context_records': sum(r['source_id'] == source_id for r in context_rows),
                'upstream_pre_dedup_records': row.get('pre_dedup_records'),
                'upstream_duplicates_removed': row.get('exact_source_text_duplicates_removed'),
                'input_file': agent_zip.name, 'input_member': forum_member,
                'context_input_member': context_member,
                'date_basis': 'relative_display_labels;exact_publication_dates_unknown',
                'coverage_scope': 'visible_rendered_subset;not_complete_thread',
            })
        emit_csv(repo / 'metadata/reddit_sources.csv', list(reddit_sources[0]), reddit_sources)
        reddit_summary['source_attempts'] = len(reddit_sources)
        reddit_summary['source_status_counts'] = dict(Counter(r['collection_status'] for r in reddit_sources))
        reddit_summary['context_rows_excluded_from_corpus'] = len(context_rows)
        reddit_summary['missing_publication_date_rows_retained'] = sum(not r['published_at'] for r in reddit.rows)
        # These are run settings in supplied provenance, not inferred from input defaults.
        collection_runs = json.loads(archive.read(prefix + 'provenance/collection_runs.json'))

    emit_csv(repo / 'reports/social_removed.csv', REMOVED_COLUMNS, removed)
    summary = {
        'text_changes': 'outer_whitespace_trim_and_NUL_removal_only',
        'deduplication': 'same_platform_source_id_and_exact_original_payload_only;different_payload_versions_retained',
        'excluded_fields': 'author_and_profile_metadata;media;redundant_URL_aliases;unused_metrics',
        'source_row_basis': '1_based_data_row_or_JSON_array_index_excluding_CSV_header',
        'input_manifests': input_manifests,
        'platforms': {'x': x_summary, 'youtube': youtube_summary, 'reddit': reddit_summary},
        'youtube_collection_runs_from_supplied_provenance': collection_runs,
        'x_run_settings': 'not_embedded_in_supplied_exports',
        'total_raw_rows': sum(s['raw_rows'] for s in [x_summary, youtube_summary, reddit_summary]),
        'total_retained_rows': sum(s['retained_rows'] for s in [x_summary, youtube_summary, reddit_summary]),
        'total_removed_rows': len(removed),
        'context_rows_excluded_from_corpus': len(context_rows) + len(quote_rows),
        'metadata_files': ['metadata/x_sources.csv', 'metadata/youtube_sources.csv',
                           'metadata/reddit_sources.csv', 'metadata/context.csv',
                           'metadata/x_quote_context.csv'],
    }
    assert summary['total_raw_rows'] == summary['total_retained_rows'] + summary['total_removed_rows']
    write_json(repo / 'reports/social_cleaning_summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--x-input', action='append', required=True)
    parser.add_argument('--agent-zip', required=True)
    args = parser.parse_args()
    summary = build_social(args.repo, args.x_input, args.agent_zip)
    print(json.dumps({k: summary[k] for k in ['total_raw_rows', 'total_retained_rows',
                                             'total_removed_rows', 'context_rows_excluded_from_corpus']}))


if __name__ == '__main__':
    main()
