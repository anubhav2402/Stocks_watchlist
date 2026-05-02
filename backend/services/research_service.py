import asyncio
import logging
import feedparser
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _fetch_google_news(symbol: str) -> list[dict]:
    url = f'https://news.google.com/rss/search?q={symbol}+stock&hl=en-US&gl=US&ceid=US:en'
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in (feed.entries or [])[:10]:
            title = getattr(entry, 'title', '').strip()
            link  = getattr(entry, 'link', '')
            date_str = ''
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                from datetime import datetime as _dt
                try:
                    date_str = _dt(*entry.published_parsed[:3]).strftime('%Y-%m-%d')
                except Exception:
                    pass
            source = ''
            if hasattr(entry, 'source') and isinstance(entry.source, dict):
                source = entry.source.get('title', '')
            if title and link:
                items.append({'title': title, 'url': link, 'publisher': source, 'date': date_str})
        return items
    except Exception as e:
        logger.warning('Google News RSS fetch failed for %s: %s', symbol, e)
        return []


def _safe(val, default=None):
    try:
        return default if (val is None or pd.isna(val)) else val
    except Exception:
        return val if val is not None else default


def _pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / abs(b) * 100, 2)


def _fmt_m(val):
    """Return value in millions as float, or None."""
    return round(val / 1e6, 2) if val is not None else None


def _row(df, *keys):
    """Extract a DataFrame row by trying multiple key names. Returns list of values (most recent first)."""
    if df is None or df.empty:
        return []
    for key in keys:
        if key in df.index:
            vals = [_safe(v) for v in df.loc[key].tolist()]
            return vals
    return []


def _row1(df, *keys):
    vals = _row(df, *keys)
    return vals[0] if vals else None


def _calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(len(closes) - period, len(closes)):
        ch = closes[i] - closes[i - 1]
        if ch > 0:
            gains += ch
        else:
            losses -= ch
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 1)


def _get_df(ticker, *attr_names):
    """Try multiple attribute names to get a DataFrame (handles yfinance API version differences)."""
    for name in attr_names:
        try:
            df = getattr(ticker, name, None)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
    return None


def _fiscal_years(df, n=4):
    """Return fiscal year strings for the first n columns of a DataFrame."""
    if df is None or df.empty:
        return []
    cols = df.columns[:n]
    return [str(c.year) if hasattr(c, 'year') else str(c)[:4] for c in cols]


def _fetch_research_sync(symbol: str) -> dict:
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}

        # Financial statements — try new API names first, fall back to old
        income = _get_df(t, 'income_stmt', 'financials')
        balance = _get_df(t, 'balance_sheet')
        cashflow = _get_df(t, 'cashflow', 'cash_flow')

        fiscal_years = _fiscal_years(income)

        # ── Income statement ──────────────────────────────────────────
        revenue      = [_fmt_m(v) for v in _row(income, 'Total Revenue')][:4]
        gross_profit = [_fmt_m(v) for v in _row(income, 'Gross Profit')][:4]
        ebitda       = [_fmt_m(v) for v in _row(income, 'Normalized EBITDA', 'EBITDA')][:4]
        ebit         = [_fmt_m(v) for v in _row(income, 'EBIT', 'Operating Income')][:4]
        net_income   = [_fmt_m(v) for v in _row(income, 'Net Income Common Stockholders', 'Net Income')][:4]
        eps_diluted  = [_safe(v) for v in _row(income, 'Diluted EPS', 'Basic EPS')][:4]

        # Derived margins (annualised, most recent first)
        def _margins(numerator, denominator):
            pairs = list(zip(numerator, denominator))
            return [round(a / b * 100, 1) if a and b else None for a, b in pairs]

        gross_margins = _margins(gross_profit, revenue)
        ebit_margins  = _margins(ebit, revenue)
        net_margins   = _margins(net_income, revenue)

        # Revenue growth YoY (index 0 = most recent year's growth)
        rev_growth = []
        for i in range(len(revenue) - 1):
            rev_growth.append(_pct(revenue[i], revenue[i + 1]))
        rev_growth.append(None)  # oldest year has no prior

        # ── Balance sheet ─────────────────────────────────────────────
        total_debt   = _fmt_m(_row1(balance, 'Total Debt'))
        total_cash   = _fmt_m(_row1(balance, 'Cash And Cash Equivalents',
                                    'Cash Cash Equivalents And Short Term Investments',
                                    'Cash Financial'))
        total_equity = _fmt_m(_row1(balance, 'Stockholders Equity',
                                    'Total Equity Gross Minority Interest'))
        goodwill     = _fmt_m(_row1(balance, 'Goodwill And Other Intangible Assets', 'Goodwill'))

        net_debt = round(total_debt - total_cash, 2) if total_debt and total_cash else None

        # ── Cash flow ─────────────────────────────────────────────────
        op_cf = [_fmt_m(v) for v in _row(cashflow, 'Operating Cash Flow',
                                          'Total Cash From Operating Activities')][:4]
        capex = [_fmt_m(v) for v in _row(cashflow, 'Capital Expenditure')][:4]

        # FCF = op_cf + capex (capex is typically negative in yfinance)
        fcf = []
        for i in range(max(len(op_cf), len(capex))):
            oc = op_cf[i] if i < len(op_cf) else None
            cx = capex[i] if i < len(capex) else None
            fcf.append(round(oc + cx, 2) if oc is not None and cx is not None else oc)

        # FCF conversion (FCF / net income)
        fcf_conv = []
        for i in range(len(fcf)):
            ni = net_income[i] if i < len(net_income) else None
            fcf_conv.append(round(fcf[i] / ni * 100, 1) if fcf[i] and ni else None)

        # Net debt / EBITDA
        nd_ebitda = None
        if net_debt and ebitda and ebitda[0]:
            nd_ebitda = round(net_debt / ebitda[0], 2)

        # ROIC estimate: NOPAT / (equity + debt - cash)
        roic = None
        if ebit and ebit[0] and total_equity and total_debt and total_cash:
            tax_rate = 0.21
            nopat = ebit[0] * (1 - tax_rate)
            invested_cap = total_equity + total_debt - total_cash
            if invested_cap > 0:
                roic = round(nopat / invested_cap * 100, 1)

        # ── Technical indicators from 1yr daily history ───────────────
        hist = t.history(period='1y', interval='1d')
        closes = hist['Close'].dropna().tolist() if not hist.empty else []
        volumes = hist['Volume'].dropna().tolist() if not hist.empty else []

        current_price = round(closes[-1], 2) if closes else _safe(
            info.get('currentPrice') or info.get('regularMarketPrice'))
        sma50  = round(sum(closes[-50:])  / 50,  2) if len(closes) >= 50  else None
        sma200 = round(sum(closes[-200:]) / 200, 2) if len(closes) >= 200 else None
        high52 = round(max(closes), 2) if closes else None
        low52  = round(min(closes), 2) if closes else None
        rsi14  = _calc_rsi(closes)
        range_pos = None
        if high52 and low52 and high52 != low52 and current_price:
            range_pos = round((current_price - low52) / (high52 - low52) * 100, 1)

        avg_vol = round(sum(volumes[-20:]) / min(20, len(volumes))) if volumes else _safe(info.get('averageVolume'))

        # ── Calendar ─────────────────────────────────────────────────
        earnings_date = None
        try:
            cal = t.calendar
            ed = cal.get('Earnings Date') if isinstance(cal, dict) else None
            if isinstance(ed, list):
                ed = ed[0]
            if ed is not None:
                earnings_date = str(pd.Timestamp(ed).date())
        except Exception:
            pass

        # ── News headlines (Google News RSS, yfinance fallback) ───────
        news_items = _fetch_google_news(symbol)
        if not news_items:
            try:
                from datetime import datetime as _dt
                raw_news = getattr(t, 'news', []) or []
                for n in raw_news[:7]:
                    ts = n.get('providerPublishTime') or n.get('content', {}).get('pubDate')
                    try:
                        date_str = _dt.fromtimestamp(int(ts)).strftime('%Y-%m-%d') if ts else ''
                    except Exception:
                        date_str = ''
                    title = n.get('title') or (n.get('content') or {}).get('title', '')
                    url = n.get('link') or (n.get('content') or {}).get('canonicalUrl', {}).get('url', '')
                    publisher = n.get('publisher') or (n.get('content') or {}).get('provider', {}).get('displayName', '')
                    if title:
                        news_items.append({'title': title, 'url': url, 'publisher': publisher, 'date': date_str})
            except Exception:
                pass

        # ── Analyst upgrades / downgrades (last 90 days) ─────────────
        upgrades = []
        try:
            from datetime import timedelta as _td, datetime as _dt2
            cutoff = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=90)
            upg_df = _get_df(t, 'upgrades_downgrades')
            if upg_df is not None:
                upg_df = upg_df.sort_index(ascending=False)
                for idx, row in upg_df.head(10).iterrows():
                    try:
                        row_date = pd.Timestamp(idx)
                        if row_date.tz is None:
                            row_date = row_date.tz_localize('UTC')
                        if row_date < cutoff:
                            continue
                    except Exception:
                        pass
                    upgrades.append({
                        'date': str(idx)[:10],
                        'firm': str(row.get('Firm', '')),
                        'from_grade': str(row.get('FromGrade', '')),
                        'to_grade': str(row.get('ToGrade', '')),
                        'action': str(row.get('Action', '')),
                    })
                    if len(upgrades) >= 8:
                        break
        except Exception:
            pass

        # ── Insider transactions (last 60 days) ──────────────────────
        insider_trades = []
        try:
            ins_df = _get_df(t, 'insider_transactions', 'insider_purchases')
            if ins_df is not None:
                for _, row in ins_df.head(6).iterrows():
                    shares = _safe(row.get('Shares') or row.get('shares'))
                    value = _safe(row.get('Value') or row.get('value'))
                    insider_trades.append({
                        'date': str(row.get('Start Date') or row.get('startDate') or row.get('Date') or '')[:10],
                        'insider': str(row.get('Insider') or row.get('insider') or ''),
                        'position': str(row.get('Position') or row.get('position') or ''),
                        'transaction': str(row.get('Transaction') or row.get('transaction') or ''),
                        'shares': int(shares) if shares else None,
                        'value': _fmt_m(shares * (_safe(info.get('currentPrice')) or 0) / 1e6) if shares else None,
                    })
        except Exception:
            pass

        # ── Earnings surprise history (last 4 quarters) ──────────────
        earnings_surprises = []
        try:
            eh_df = _get_df(t, 'earnings_history')
            if eh_df is not None and not eh_df.empty:
                for _, row in eh_df.head(4).iterrows():
                    est = _safe(row.get('epsEstimate') or row.get('EPS Estimate'))
                    act = _safe(row.get('epsActual') or row.get('EPS Actual'))
                    surprise_pct = round((act - est) / abs(est) * 100, 1) if est and act and est != 0 else None
                    earnings_surprises.append({
                        'period': str(row.get('quarter') or row.get('Quarter') or '')[:10],
                        'estimate': est,
                        'actual': act,
                        'surprise_pct': surprise_pct,
                    })
        except Exception:
            pass

        # ── Quarterly income (last 4 quarters) ───────────────────────
        q_periods, q_revenue, q_gross_profit, q_ebit, q_net_income, q_eps, q_rev_growth = [], [], [], [], [], [], []
        try:
            q_income = _get_df(t, 'quarterly_income_stmt', 'quarterly_financials')
            if q_income is not None and not q_income.empty:
                q_periods = [col.strftime('%b %Y') for col in q_income.columns[:4]]
                q_rev_raw      = _row(q_income, 'Total Revenue')[:4]
                q_gross_profit = [_fmt_m(v) for v in _row(q_income, 'Gross Profit')[:4]]
                q_ebit         = [_fmt_m(v) for v in _row(q_income, 'EBIT', 'Operating Income')[:4]]
                q_net_income   = [_fmt_m(v) for v in _row(q_income, 'Net Income Common Stockholders', 'Net Income')[:4]]
                q_eps          = [_safe(v) for v in _row(q_income, 'Diluted EPS', 'Basic EPS')[:4]]
                q_revenue      = [_fmt_m(v) for v in q_rev_raw]
                q_rev_growth   = []
                for i, curr in enumerate(q_rev_raw):
                    prev = q_rev_raw[i + 1] if i + 1 < len(q_rev_raw) else None
                    if curr is not None and prev is not None and prev != 0:
                        q_rev_growth.append(round((curr - prev) / abs(prev) * 100, 1))
                    else:
                        q_rev_growth.append(None)
        except Exception:
            pass

        # ── Forward analyst estimates (CY + NY revenue & EPS) ────────
        revenue_estimates, eps_estimates = [], []
        try:
            rev_est = t.revenue_estimate
            if rev_est is not None and not rev_est.empty:
                for period_key, period_label in [('0y', 'Current Year'), ('+1y', 'Next Year')]:
                    if period_key in rev_est.index:
                        r = rev_est.loc[period_key]
                        revenue_estimates.append({
                            'period': period_label,
                            'avg': _safe(r.get('avg')),
                            'low': _safe(r.get('low')),
                            'high': _safe(r.get('high')),
                            'growth': _safe(r.get('growth')),
                            'num_analysts': int(r.get('numberOfAnalysts') or 0),
                        })
        except Exception:
            pass
        try:
            eps_est = t.earnings_estimate
            if eps_est is not None and not eps_est.empty:
                for period_key, period_label in [('0y', 'Current Year'), ('+1y', 'Next Year')]:
                    if period_key in eps_est.index:
                        r = eps_est.loc[period_key]
                        eps_estimates.append({
                            'period': period_label,
                            'avg': _safe(r.get('avg')),
                            'growth': _safe(r.get('growth')),
                            'year_ago_eps': _safe(r.get('yearAgoEps')),
                            'num_analysts': int(r.get('numberOfAnalysts') or 0),
                        })
        except Exception:
            pass

        mktcap = _safe(info.get('marketCap'))

        return {
            # Identity
            'ticker': symbol,
            'name': info.get('longName') or info.get('shortName') or symbol,
            'sector': info.get('sector') or '',
            'industry': info.get('industry') or '',
            'country': info.get('country') or '',
            'description': info.get('longBusinessSummary') or '',
            'website': info.get('website') or '',
            'employees': _safe(info.get('fullTimeEmployees')),
            'currency': info.get('currency') or 'USD',

            # Price & size
            'price': current_price,
            'market_cap_m': _fmt_m(mktcap),
            'enterprise_value_m': _fmt_m(_safe(info.get('enterpriseValue'))),

            # Valuation multiples
            'pe': round(_safe(info.get('trailingPE'), 0), 2) or None,
            'fwd_pe': round(_safe(info.get('forwardPE'), 0), 2) or None,
            'pb': round(_safe(info.get('priceToBook'), 0), 2) or None,
            'ps': round(_safe(info.get('priceToSalesTrailing12Months'), 0), 2) or None,
            'ev_ebitda': round(_safe(info.get('enterpriseToEbitda'), 0), 2) or None,
            'ev_revenue': round(_safe(info.get('enterpriseToRevenue'), 0), 2) or None,
            'dividend_yield': _safe(info.get('dividendYield')),
            'payout_ratio': _safe(info.get('payoutRatio')),

            # Margins & returns
            'gross_margin_pct': round(_safe(info.get('grossMargins'), 0) * 100, 1) or None,
            'op_margin_pct': round(_safe(info.get('operatingMargins'), 0) * 100, 1) or None,
            'net_margin_pct': round(_safe(info.get('profitMargins'), 0) * 100, 1) or None,
            'roe': round(_safe(info.get('returnOnEquity'), 0) * 100, 1) or None,
            'roa': round(_safe(info.get('returnOnAssets'), 0) * 100, 1) or None,
            'roic': roic,
            'debt_to_equity': _safe(info.get('debtToEquity')),
            'current_ratio': _safe(info.get('currentRatio')),

            # Liquidity & positioning
            'beta': _safe(info.get('beta')),
            'avg_volume': avg_vol,
            'float_shares_m': _fmt_m(_safe(info.get('floatShares'))),
            'short_percent': round(_safe(info.get('shortPercentOfFloat'), 0) * 100, 2) or None,
            'short_ratio': _safe(info.get('shortRatio')),
            'insider_pct': round(_safe(info.get('heldPercentInsiders'), 0) * 100, 1) or None,
            'institution_pct': round(_safe(info.get('heldPercentInstitutions'), 0) * 100, 1) or None,

            # Analyst consensus
            'target_mean': _safe(info.get('targetMeanPrice')),
            'target_high': _safe(info.get('targetHighPrice')),
            'target_low': _safe(info.get('targetLowPrice')),
            'recommendation': info.get('recommendationKey') or '',
            'num_analysts': _safe(info.get('numberOfAnalystOpinions')),
            'fwd_eps': _safe(info.get('forwardEps')),
            'trailing_eps': _safe(info.get('trailingEps')),

            # Income statement (4yr, most recent first), values in $M
            'fiscal_years': fiscal_years,
            'revenue': revenue,
            'gross_profit': gross_profit,
            'ebitda': ebitda,
            'ebit': ebit,
            'net_income': net_income,
            'eps_diluted': eps_diluted,
            'gross_margins': gross_margins,
            'ebit_margins': ebit_margins,
            'net_margins': net_margins,
            'rev_growth': rev_growth,

            # Balance sheet ($M)
            'total_debt': total_debt,
            'total_cash': total_cash,
            'total_equity': total_equity,
            'goodwill': goodwill,
            'net_debt': net_debt,
            'nd_ebitda': nd_ebitda,

            # Cash flow ($M, 4yr)
            'op_cf': op_cf,
            'capex': capex,
            'fcf': fcf,
            'fcf_conv': fcf_conv,

            # Derived
            'roic': roic,

            # Technicals
            'sma50': sma50,
            'sma200': sma200,
            'price_vs_50': _pct(current_price, sma50),
            'price_vs_200': _pct(current_price, sma200),
            'rsi14': rsi14,
            'high_52w': high52,
            'low_52w': low52,
            'range_pos_52w': range_pos,

            # Calendar
            'earnings_date': earnings_date,

            # Activity feeds
            'news_items': news_items,
            'upgrades': upgrades,
            'insider_trades': insider_trades,
            'earnings_surprises': earnings_surprises,

            # Quarterly income ($M, most recent first)
            'q_periods': q_periods,
            'q_revenue': q_revenue,
            'q_gross_profit': q_gross_profit,
            'q_ebit': q_ebit,
            'q_net_income': q_net_income,
            'q_eps': q_eps,
            'q_rev_growth': q_rev_growth,

            # Forward analyst estimates
            'revenue_estimates': revenue_estimates,
            'eps_estimates': eps_estimates,
        }

    except Exception as e:
        logger.warning("research_service: failed for %s: %s", symbol, e)
        return {'ticker': symbol, 'error': str(e), 'name': symbol}


async def fetch_research_fundamentals(symbol: str) -> dict:
    return await asyncio.to_thread(_fetch_research_sync, symbol)
