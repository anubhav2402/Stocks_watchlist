"""
LLM-powered research analysis for the Research Workbench.

Takes pre-fetched fundamentals + Twitter buzz + user's investment profile,
calls Claude Haiku, returns commentary, valuation verdict, and recommendation.
Cached 12h per ticker (cache is investment-profile-agnostic for cost reasons;
use force_refresh=True to regenerate with a different profile).
"""

import json
import logging
import os
from datetime import datetime, timezone

from services.cache_service import research_analysis_cache
from services.buzz_engine import get_alert_for_ticker

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a financial analyst assistant for an individual investor.
Given a stock's financial data, recent news, and the investor's personal profile,
return ONLY a JSON object with EXACTLY this shape (no markdown, no extra keys):
{
  "financials_commentary": "<2-3 sentences on revenue/margin trends, FCF quality, and any red flags>",
  "forward_outlook": "<1-2 sentences on where earnings and growth appear headed based on trends and consensus>",
  "valuation_verdict": "<1-2 sentences on whether the stock is cheap, fair, or expensive vs its own history and the investor's criteria>",
  "recommendation": "BUY" | "HOLD" | "PASS" | "SELL",
  "recommendation_score": <float 1-10, where 8-10=strong buy, 6-7=buy, 4-5=hold, 1-3=pass/sell>,
  "reasoning": "<3-4 sentences explaining the recommendation, directly referencing the investor's stated criteria>",
  "key_risks": ["<specific risk 1>", "<specific risk 2>", "<specific risk 3>"]
}

Be direct and specific — cite actual numbers from the data. No generic statements.
Align the recommendation with the investor's stated profile and criteria.\
"""


def _fmt(val, decimals=1, suffix='', scale=1.0):
    if val is None:
        return 'N/A'
    try:
        return f'{float(val) * scale:.{decimals}f}{suffix}'
    except Exception:
        return 'N/A'


def _fmt_m(val):
    if val is None:
        return 'N/A'
    if abs(val) >= 1000:
        return f'${val/1000:.1f}B'
    return f'${val:.0f}M'


def _build_prompt(symbol: str, d: dict, investment_profile: str) -> str:
    # Format 4-yr financials compactly
    yrs = d.get('fiscal_years', [])[:4]
    rev = d.get('revenue', [])
    ni = d.get('net_income', [])
    fcf = d.get('fcf', [])
    gm = d.get('gross_margins', [])
    rev_g = d.get('rev_growth', [])

    def yr_row(label, vals, fmt_fn):
        cells = ' | '.join(fmt_fn(vals[i]) if i < len(vals) else 'N/A' for i in range(len(yrs)))
        return f'  {label}: {cells}'

    fin_block = ''
    if yrs:
        header = '  Years: ' + ' | '.join(f'FY{y}' for y in yrs)
        fin_block = '\n'.join([
            header,
            yr_row('Revenue', rev, _fmt_m),
            yr_row('Rev Growth', rev_g, lambda v: _fmt(v, 1, '%') if v is not None else 'N/A'),
            yr_row('Gross Margin', gm, lambda v: _fmt(v, 1, '%') if v is not None else 'N/A'),
            yr_row('Net Income', ni, _fmt_m),
            yr_row('Free CF', fcf, _fmt_m),
        ])

    # News headlines
    news_block = ''
    news = d.get('news_items', [])
    if news:
        news_block = 'Recent News:\n' + '\n'.join(f'  - [{n["date"]}] {n["title"]}' for n in news[:5])

    # Analyst actions
    upg_block = ''
    upgrades = d.get('upgrades', [])
    if upgrades:
        upg_block = 'Analyst Actions (last 90d):\n' + '\n'.join(
            f'  - {u["date"]} {u["firm"]}: {u["from_grade"] or "—"} → {u["to_grade"]} ({u["action"]})'
            for u in upgrades[:5]
        )

    # MRQ snapshot
    mrq_block = ''
    q_periods = d.get('q_periods', [])
    if q_periods:
        qr  = (d.get('q_revenue')    or [None])[0]
        qni = (d.get('q_net_income') or [None])[0]
        qg  = (d.get('q_rev_growth') or [None])[0]
        mrq_block = (
            f'Most Recent Quarter ({q_periods[0]}): '
            f'Rev={_fmt_m(qr)} | Net Income={_fmt_m(qni)} | '
            f'QoQ Rev Growth={_fmt(qg, 1, "%") if qg is not None else "N/A"}'
        )

    # Forward analyst consensus estimates
    fwd_block = ''
    rev_ests = d.get('revenue_estimates', [])
    eps_ests = d.get('eps_estimates', [])
    if rev_ests or eps_ests:
        rows = []
        for r in rev_ests:
            g = f' ({r["growth"] * 100:+.0f}% YoY)' if r.get('growth') is not None else ''
            # avg is raw dollars — convert to $M for _fmt_m
            avg_m = float(r['avg']) / 1e6 if r.get('avg') is not None else None
            rows.append(f'  {r["period"]} Revenue: {_fmt_m(avg_m)} consensus{g}')
        for e in eps_ests:
            g = f' ({e["growth"] * 100:+.0f}% YoY)' if e.get('growth') is not None else ''
            rows.append(f'  {e["period"]} EPS: ${_fmt(e["avg"], 2)} consensus{g}')
        fwd_block = 'Analyst Consensus Estimates (forward):\n' + '\n'.join(rows)

    # Twitter buzz for this ticker
    buzz_block = ''
    try:
        alert = get_alert_for_ticker(symbol)
        if alert and alert.mentions:
            tweets = [m.text for m in alert.mentions[-3:] if m.text]
            if tweets:
                buzz_block = 'Social/Twitter mentions:\n' + '\n'.join(f'  - {t[:200]}' for t in tweets)
    except Exception:
        pass

    profile_section = investment_profile.strip() if investment_profile.strip() else 'No profile provided — use general value/growth criteria.'

    lines = [
        f'Investor Profile: {profile_section}',
        '',
        f'Ticker: {symbol} | {d.get("name", symbol)} | {d.get("sector", "")} · {d.get("industry", "")}',
        f'Price: {d.get("currency","$")} {d.get("price", "N/A")} | Mkt Cap: {_fmt_m(d.get("market_cap_m"))}',
        f'Valuation: P/E={_fmt(d.get("pe"),1,"x")} | Fwd P/E={_fmt(d.get("fwd_pe"),1,"x")} | EV/EBITDA={_fmt(d.get("ev_ebitda"),1,"x")} | EV/Rev={_fmt(d.get("ev_revenue"),2,"x")}',
        f'Margins: Gross={_fmt(d.get("gross_margin_pct"),1,"%")} | Op={_fmt(d.get("op_margin_pct"),1,"%")} | Net={_fmt(d.get("net_margin_pct"),1,"%")}',
        f'Returns: ROE={_fmt(d.get("roe"),1,"%")} | ROA={_fmt(d.get("roa"),1,"%")} | ROIC={_fmt(d.get("roic"),1,"%")}',
        f'Balance Sheet: Net Debt={_fmt_m(d.get("net_debt"))} | Net Debt/EBITDA={_fmt(d.get("nd_ebitda"),2,"x")}',
        f'Analyst: Target Mean={d.get("target_mean","N/A")} | Rec={d.get("recommendation","N/A")} | Analysts={d.get("num_analysts","N/A")}',
        f'Technical: RSI={d.get("rsi14","N/A")} | vs50DMA={_fmt(d.get("price_vs_50"),1,"%")} | vs200DMA={_fmt(d.get("price_vs_200"),1,"%")}',
        '',
        '4-Year Financials ($M):',
        fin_block,
    ]
    if mrq_block:
        lines += ['', mrq_block]
    if fwd_block:
        lines += ['', fwd_block]
    if news_block:
        lines += ['', news_block]
    if upg_block:
        lines += ['', upg_block]
    if buzz_block:
        lines += ['', buzz_block]

    return '\n'.join(lines)


def _call_llm(symbol: str, prompt: str) -> dict | None:
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        logger.warning('ANTHROPIC_API_KEY not set — skipping research analysis')
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=700,
            system=_SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
            raw = raw.strip()
        logger.info('research_analysis LLM response for %s: %s', symbol, raw[:120])
        return json.loads(raw)
    except Exception as e:
        logger.warning('research_analysis LLM call failed for %s: %s', symbol, e)
        return None


def fetch_analysis(symbol: str, investment_profile: str, force_refresh: bool = False) -> dict:
    cache_key = symbol
    if not force_refresh and cache_key in research_analysis_cache:
        result = research_analysis_cache[cache_key]
        return {**result, 'cached': True}

    # We need the fundamentals — import here to avoid circular imports
    from services.research_service import _fetch_research_sync
    d = _fetch_research_sync(symbol)

    # Capture buzz mentions to include in response
    buzz_mentions = []
    try:
        alert = get_alert_for_ticker(symbol)
        if alert and alert.mentions:
            buzz_mentions = [
                {'account': m.account, 'text': m.text, 'sentiment': m.sentiment_label, 'timestamp': m.timestamp}
                for m in alert.mentions[-5:] if m.text
            ]
    except Exception:
        pass

    prompt = _build_prompt(symbol, d, investment_profile)
    llm = _call_llm(symbol, prompt)

    if llm is None:
        result = {
            'ticker': symbol,
            'error': 'LLM analysis unavailable',
            'buzz_mentions': buzz_mentions,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'cached': False,
        }
        return result

    result = {
        'ticker': symbol,
        'financials_commentary': llm.get('financials_commentary', ''),
        'forward_outlook': llm.get('forward_outlook', ''),
        'valuation_verdict': llm.get('valuation_verdict', ''),
        'recommendation': llm.get('recommendation', 'PASS'),
        'recommendation_score': max(1.0, min(10.0, float(llm.get('recommendation_score', 5)))),
        'reasoning': llm.get('reasoning', ''),
        'key_risks': llm.get('key_risks', []),
        'buzz_mentions': buzz_mentions,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'cached': False,
    }
    research_analysis_cache[cache_key] = result
    return result
