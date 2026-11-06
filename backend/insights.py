"""MoneyFlow v1.0.26 local-only, read-only financial insight heuristics.

The suggestions are not predictions of fraud or authenticated merchants. Inputs
must already be scoped to the current user by the API layer.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from calendar import monthrange
from datetime import date
from statistics import median
import re
import unicodedata


def normalize_title(value: str) -> str:
    # Accent/case-insensitive search for Vietnamese transaction descriptions.
    value = unicodedata.normalize('NFD', (value or '').casefold().replace('đ', 'd'))
    value = ''.join(c for c in value if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', re.sub('[^a-z0-9]+', ' ', value)).strip()


def month_index(value: date) -> int:
    return value.year * 12 + value.month - 1


def month_key(idx: int) -> str:
    year, month = divmod(idx, 12)
    return f'{year:04d}-{month + 1:02d}'


def score_titles(query: str, other: str) -> float:
    a, b = normalize_title(query), normalize_title(other)
    if not a or not b or len(a) < 3:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 7 and (a.startswith(b + ' ') or b.startswith(a + ' ')):
        return 0.87
    a_tokens = {t for t in a.split() if len(t) >= 3}
    b_tokens = {t for t in b.split() if len(t) >= 3}
    overlap = a_tokens & b_tokens
    union = a_tokens | b_tokens
    if len(overlap) >= 2 and union:
        similarity = len(overlap) / len(union)
        return min(0.85, 0.55 + similarity * 0.3) if similarity >= 0.5 else 0.0
    return 0.0


def suggest_categories(title: str, entries: list[dict], categories: dict[int, dict], limit: int = 3) -> list[dict]:
    """Rank only categories backed by the user's existing same-kind examples."""
    matches: dict[int, list[float]] = defaultdict(list)
    for entry in entries:
        category = categories.get(entry['category_id'])
        if not category or not category['active']:
            continue
        score = score_titles(title, entry['title'])
        if score >= 0.7:
            matches[entry['category_id']].append(score)
    total = sum(len(scores) for scores in matches.values())
    suggestions = []
    for category_id, scores in matches.items():
        strongest = max(scores)
        count = len(scores)
        # Label is qualitative evidence, not a machine-learning confidence probability.
        strength = 'cao' if strongest >= 1 and count >= 2 else 'tham khảo'
        suggestions.append({'category_id': category_id,
                            'category': categories[category_id]['name'],
                            'color': categories[category_id]['color'],
                            'examples': count, 'strength': strength,
                            '_sort': strongest * (1 + min(count, 5) / 12) + count / max(1, total) / 6})
    suggestions.sort(key=lambda s: (-s['_sort'], -s['examples'], s['category_id']))
    for suggestion in suggestions:
        suggestion.pop('_sort')
    return suggestions[:limit]


def spending_insights(entries: list[dict], categories: dict[int, dict],
                      recurring_rules: list[dict], now: date, months: int,
                      sample_limited: bool = False) -> dict:
    """Past months are full, current month is explicitly partial/projected."""
    current_index = month_index(now)
    start_index = current_index - months + 1
    spending = [e for e in entries if e['kind'] == 'expense' and
                start_index <= month_index(e['occurred_on']) <= current_index and
                e['occurred_on'] <= now]
    amounts_by_month: dict[int, int] = defaultdict(int)
    categories_by_month: dict[tuple[int, int], int] = defaultdict(int)
    groups: dict[tuple[str, int, int | None], list[dict]] = defaultdict(list)
    category_totals: dict[int, int] = defaultdict(int)
    for e in spending:
        idx = month_index(e['occurred_on'])
        amount = int(e['amount'])
        amounts_by_month[idx] += amount
        category_totals[e['category_id']] += amount
        categories_by_month[(idx, e['category_id'])] += amount
        normalized = normalize_title(e['title'])
        if len(normalized) >= 5:
            groups[(normalized, e['category_id'], e.get('wallet_id'))].append(e)

    timeline = [{'month': month_key(i), 'expense': amounts_by_month[i],
                 'partial': i == current_index} for i in range(start_index, current_index + 1)]
    previous = [amounts_by_month[i] for i in range(start_index, current_index)]
    previous_average = round(sum(previous) / len(previous)) if previous else 0
    days_in_month = monthrange(now.year, now.month)[1]
    # Do not multiply an unusually large first-day purchase by 31.
    projected = round(amounts_by_month[current_index] * days_in_month / now.day) if now.day >= 5 else None
    tops = sorted(category_totals.items(), key=lambda pair: (-pair[1], pair[0]))[:8]
    top_categories = [{'category_id': category_id,
                       'category': categories.get(category_id, {}).get('name', 'Danh mục không còn'),
                       'color': categories.get(category_id, {}).get('color', '#7567F8'),
                       'amount': total} for category_id, total in tops]

    alerts = []
    if not sample_limited and now.day >= 5 and months >= 3:
        for category_id in category_totals:
            older = [categories_by_month[(i, category_id)] for i in range(start_index, current_index)]
            nonzero_months = sum(v > 0 for v in older)
            baseline = sum(older) / len(older)
            current_spent = categories_by_month[(current_index, category_id)]
            estimated = round(current_spent * days_in_month / now.day)
            if nonzero_months >= 2 and baseline >= 100_000 and estimated >= baseline * 1.5 and estimated - baseline >= 150_000:
                alerts.append({'category_id': category_id,
                               'category': categories.get(category_id, {}).get('name', 'Danh mục không còn'),
                               'baseline_monthly': round(baseline), 'spent_to_date': current_spent,
                               'projected_monthly': estimated,
                               'estimated_increase_pct': round((estimated / baseline - 1) * 100),
                               'reason': 'Mức chi dự kiến cao hơn trung bình các tháng trước; chỉ là ước tính theo tốc độ chi hiện tại.'})
    alerts.sort(key=lambda item: (-item['estimated_increase_pct'], item['category_id']))

    scheduled = {(normalize_title(r['title']), r['category_id'], r.get('wallet_id'))
                 for r in recurring_rules if r['kind'] == 'expense' and r.get('active')}
    repeat_candidates = []
    if not sample_limited:
        for key, occurrences in groups.items():
            if key in scheduled:
                continue
            per_month: dict[int, list[dict]] = defaultdict(list)
            for item in occurrences:
                per_month[month_index(item['occurred_on'])].append(item)
            month_ids = sorted(per_month)
            if len(month_ids) < 3 or any(len(rows) != 1 for rows in per_month.values()):
                continue
            longest_run, run = 1, 1
            for previous_month, current_month in zip(month_ids, month_ids[1:]):
                run = run + 1 if current_month == previous_month + 1 else 1
                longest_run = max(longest_run, run)
            if longest_run < 3:
                continue
            amounts = [int(item['amount']) for item in occurrences]
            days = [item['occurred_on'].day for item in occurrences]
            if min(amounts) <= 0 or max(amounts) > min(amounts) * 1.35:
                continue
            if max(days) - min(days) > 7:
                continue
            latest = max(occurrences, key=lambda item: item['occurred_on'])
            repeat_candidates.append({'title': latest['title'], 'category_id': key[1],
                                      'category': categories.get(key[1], {}).get('name', 'Danh mục không còn'),
                                      'wallet_id': key[2], 'months_seen': len(month_ids),
                                      'consecutive_months': longest_run,
                                      'typical_amount': round(median(amounts)),
                                      'typical_day': round(median(days)),
                                      'last_on': latest['occurred_on'].isoformat()})
    repeat_candidates.sort(key=lambda item: (-item['consecutive_months'], -item['typical_amount'], item['title']))
    return {'months': months, 'from_month': month_key(start_index),
            'to_month': month_key(current_index), 'as_of': now.isoformat(),
            'total_expense': sum(amounts_by_month.values()), 'transaction_count': len(spending),
            'current_month_spent': amounts_by_month[current_index],
            'previous_month_average': previous_average,
            'current_month_projection': projected, 'monthly': timeline,
            'top_categories': top_categories, 'alerts': alerts[:8],
            'recurring_candidates': repeat_candidates[:8],
            'sample_limited': sample_limited,
            'disclaimer': 'Phân tích quy tắc từ dữ liệu của chính bạn, không phải kết luận gian lận. Dự báo tháng hiện tại là ước tính; không tự thay đổi giao dịch.'}
