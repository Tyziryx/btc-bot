# Polymarket BTC 5-Minute Trading Bot — Design Spec V3 (PRO)

## Overview

Bot de trading professionnel pour les marchés "Bitcoin Up or Down" 5 minutes sur Polymarket. Combine un modèle XGBoost calibré avec une stratégie d'arbitrage sub-$1 pour maximiser l'edge. Déployé sur serveur Irlande 24/7 avec gestion de risque institutionnelle.

---

## Phases du projet

### Phase 1 — Data Collection & Feature Engineering (local)
1. Télécharger 3 mois de klines 1min BTC/USDT + trades individuels depuis Binance REST API
2. Télécharger les funding rates historiques BTC perpetual (Binance Futures)
3. Construire les 16 features et les labels (UP/DOWN par fenêtre 5min)
4. Explorer les features (corrélations, SHAP values, importance)

### Phase 2 — Entraînement & Calibration (local)
1. Entraînement XGBoost avec cross-validation temporelle (TimeSeriesSplit)
2. Optimisation hyperparamètres par Optuna (bayesian optimization)
3. Calibration des probabilités par Isotonic Regression sur holdout set
4. Validation finale : profit factor, Sharpe, drawdown sur 1 mois out-of-sample

### Phase 3 — Backtest réaliste (local)
1. Simulation avec fill rate réaliste, fees, latence
2. Stress test sur périodes de haute volatilité (CPI, FOMC)
3. Monte Carlo simulation pour estimer la distribution des outcomes

### Phase 4 — Paper Trading (local ou serveur)
1. Bot connecté en temps réel, simule les trades sans argent
2. Minimum 500 trades simulés avant passage en prod
3. Validation que les métriques live matchent le backtest

### Phase 5 — Production (serveur Irlande)
1. Déploiement sur VPS Linux
2. Trading 24/7 avec pauses automatiques
3. Capital initial petit (~100-200$), scale up si profitable après 2 semaines
4. Retrain automatique + alertes Discord/Telegram

---

## Architecture

```
bot/
├── config.py              # Clés API, paramètres, seuils
├── data_pipeline.py       # Binance WS + REST + Polymarket WS + CLOB API
├── features.py            # Calcul des 16 features
├── model.py               # XGBoost : train, predict, calibrate, retrain
├── strategy_predict.py    # Stratégie A : prédiction ML
├── strategy_arb.py        # Stratégie B : arbitrage sub-$1
├── trading.py             # Ordres, cancel, positions, market identification
├── risk.py                # Quarter-Kelly, stops, circuit breaker, régime
├── backtest.py            # Simulation offline avec fill rate réaliste
├── bot.py                 # Orchestrateur principal (les deux stratégies)
└── utils/
    ├── logger.py          # Logging de chaque trade + décision (SQLite)
    ├── alerts.py          # Alertes Discord/Telegram
    └── calendar.py        # Calendrier macro (FOMC, CPI, NFP)
```

---

## Data Pipeline

### Sources temps réel (production)

| Source | Endpoint | Données | Auth |
|--------|----------|---------|------|
| Binance WS klines | `wss://stream.binance.com` | OHLCV 1min BTC/USDT | Non |
| Binance WS bookTicker | `wss://stream.binance.com` | Best bid/ask + qty en temps réel | Non |
| Binance WS aggTrades | `wss://stream.binance.com` | Trades individuels (pour CVD) | Non |
| Polymarket RTDS | `wss://ws-live-data.polymarket.com` | Prix BTC que Polymarket voit | Non (Binance source) |
| Polymarket CLOB | `https://clob.polymarket.com` | Orderbook, ordres, positions | Oui (L2 HMAC) |
| Binance REST Futures | `https://fapi.binance.com` | Funding rate, Open Interest | Non |

### Sources historiques (entraînement)

| Source | Données | Volume |
|--------|---------|--------|
| Binance REST klines 1min | OHLCV BTC/USDT 3 mois | ~130,000 bougies |
| Binance REST aggTrades | Trades individuels 3 mois | ~millions de trades |
| Binance REST Futures | Funding rate historique | 1 valeur / 8h |

### Stockage
- **Parquet** pour données historiques (compressé, rapide en lecture pandas)
- **Deque en mémoire** (~120 bougies 1min) pour temps réel
- **SQLite** pour logs des trades et métriques

### Labels
- Chaque fenêtre 5min : si `close_5min >= open_5min` → UP (1), sinon DOWN (0)
- Construit depuis les klines Binance (même source que le settlement Chainlink)
- Biais structurel : flat = UP → ~50.5-51.5% de bougies vertes historiquement

### Synchronisation horloge
- NTP sync obligatoire sur le serveur (< 50ms de drift)
- Les fenêtres 5min sont déterministes : `window_ts = unix_ts // 300 * 300`

---

## Features (16)

### Catégorie 1 : Direction dans la fenêtre (poids dominant)

| # | Feature | Calcul | Rôle |
|---|---------|--------|------|
| 1 | **Window Delta** | `(prix_actuel - prix_open_fenêtre) / prix_open_fenêtre` | Direction accumulée dans la fenêtre (LE PLUS IMPORTANT) |
| 2 | **Micro Momentum** | Somme des returns des 2 dernières bougies 1min | Direction court terme immédiate |
| 3 | **Acceleration** | `momentum_actuel - momentum_précédent` | Momentum qui accélère ou ralentit |

### Catégorie 2 : Order Flow (edge informationnel)

| # | Feature | Calcul | Rôle |
|---|---------|--------|------|
| 4 | **CVD (Cumulative Volume Delta)** | `sum(buy_volume - sell_volume)` sur 5 dernières minutes (via aggTrades) | Pression acheteuse vs vendeuse |
| 5 | **Bid-Ask Imbalance** | `(best_bid_qty - best_ask_qty) / (best_bid_qty + best_ask_qty)` | Déséquilibre immédiat du carnet |
| 6 | **VWAP Deviation** | `(prix_actuel - VWAP_5min) / VWAP_5min` | Prix vs prix moyen pondéré par volume |

### Catégorie 3 : Tendance & Momentum

| # | Feature | Calcul | Rôle |
|---|---------|--------|------|
| 7 | **EMA 9/21 Cross** | `(EMA9 - EMA21) / EMA21` sur klines 1min | Tendance court terme |
| 8 | **RSI 14** | RSI standard sur 14 bougies 1min | Surachat/survente (poids double si < 25 ou > 75) |
| 9 | **Z-Score** | `(prix - SMA20) / std20` | Mean reversion signal |

### Catégorie 4 : Volatilité & Régime

| # | Feature | Calcul | Rôle |
|---|---------|--------|------|
| 10 | **Bollinger Bandwidth** | `(BB_upper - BB_lower) / BB_middle` période 20 | Régime : squeeze vs expansion |
| 11 | **Volatilité réalisée 15min** | `std(returns)` sur 15 dernières bougies 1min | Niveau de bruit ambiant |
| 12 | **Volume Ratio** | `volume_actuel / mean(volume_3_dernières)` | Confirmation par volume |

### Catégorie 5 : Microstructure & Contexte

| # | Feature | Calcul | Rôle |
|---|---------|--------|------|
| 13 | **Candle Body Ratio** | `abs(close - open) / (high - low + 1e-10)` | Force directionnelle |
| 14 | **Funding Rate** | Dernier funding rate BTC perpetual (Binance Futures) | Sentiment marché dérivés |
| 15 | **Minute in Window** | Position dans la fenêtre 5min (0-4) | Contexte temporel intra-fenêtre |
| 16 | **Hour of Day** | Heure UTC (0-23), encodée cyclique (sin/cos) | Saisonnalité intraday |

### Encodage spéciaux
- **Hour of Day** encodé en 2 features : `sin(2π * hour/24)` et `cos(2π * hour/24)` pour capturer la cyclicité (→ 17 features input réelles)
- Toutes les features sont calculées au moment de la prédiction (T-30s à T-10s)

### Regime Adaptation
- Pendant les **squeezes** (BB Bandwidth < percentile 20) : le modèle sera naturellement plus sensible aux signaux de mean reversion (Z-Score, RSI)
- Pendant les **expansions** (BB Bandwidth > percentile 80) : momentum domine
- XGBoost apprend ces interactions automatiquement via les splits d'arbres

---

## Modèle XGBoost

### Configuration
- **Type** : Classification binaire (UP=1, DOWN=0)
- **Output brut** : Probabilité UP (0.0 à 1.0)
- **Output calibré** : Probabilité calibrée via Isotonic Regression
- **Confiance** : `confidence = abs(prob_calibrée - 0.5) * 2` (0.0 à 1.0)
- **Données** : Rolling window 2 mois (~25,000 échantillons de 5min)

### Hyperparamètres (optimisés par Optuna)
```python
search_space = {
    'max_depth': (2, 6),              # Peu profond = moins d'overfitting
    'n_estimators': (100, 800),
    'learning_rate': (0.005, 0.1),     # Log-uniform
    'subsample': (0.6, 0.95),
    'colsample_bytree': (0.5, 0.95),
    'min_child_weight': (5, 100),      # Régularisation forte
    'gamma': (0, 5),                   # Pruning
    'reg_alpha': (0, 10),              # L1
    'reg_lambda': (1, 10),             # L2
}
# Objectif Optuna : maximiser le profit_factor en CV temporelle, PAS l'AUC
```

### Calibration des probabilités
```python
from sklearn.calibration import CalibratedClassifierCV
from sklearn.isotonic import IsotonicRegression

# Après entraînement XGBoost :
# 1. Split : 70% train, 15% calibration, 15% test (temporel)
# 2. Entraîner XGBoost sur train
# 3. Calibrer sur calibration set avec Isotonic Regression
# 4. Évaluer sur test

calibrator = IsotonicRegression(out_of_bounds='clip')
calibrator.fit(xgb_proba_on_cal_set, y_cal)
calibrated_proba = calibrator.predict(xgb_proba_on_test)
```

### Validation
- **Méthode** : Cross-validation temporelle (TimeSeriesSplit, 5 folds)
- **Seuils minimum pour aller en prod** :
  - Profit Factor > 1.15 en backtest réaliste (avec fill rate et fees)
  - Accuracy > 57% sur le top 20% de confiance
  - Brier Score < 0.24 (meilleur que le hasard calibré)
  - Sharpe Ratio > 1.0 annualisé
  - Max Drawdown < 10% en backtest

### Retrain
- **Adaptatif** : Brier score glissant (100 derniers trades) > 0.26 → retrain auto
- **Calendaire** : toutes les 2 semaines comme filet de sécurité
- **Process** : sauvegarde ancien modèle → retrain → si nouveau modèle passe validation → swap, sinon rollback
- **Ne PAS trader pendant le retrain** (~2-5 min)

### Feature Importance dynamique
- À chaque retrain, calculer les SHAP values
- Logger les feature importances pour détecter les drifts
- Si une feature perd toute importance → flag pour investigation

---

## Stratégie A : Prédiction ML

### Cycle par fenêtre 5min

```
T-300s : Nouvelle fenêtre détectée (Unix timestamp % 300 == 0)
         Identifier le marché : slug = f"btc-updown-5m-{window_ts}"
         Récupérer condition_id et token_ids (UP et DOWN) via API
T-300s → T-30s : Collecte données, calcul features en continu
T-30s : Prédiction initiale du modèle (prob calibrée)
         Vérifier : confiance >= 60% ET edge vs orderbook >= 3 cents
T-30s → T-10s : Mise à jour continue de la prédiction chaque 2-3s
         Si conditions remplies → placer ordre limite GTC PostOnly
         Spike detection : si confiance bondit de >15% en 5s → entrée immédiate
T-5s : Cancel tous les ordres non remplis (client.cancel_all())
T-0s : Settlement automatique, logger le résultat
```

### Prix d'entrée adaptatif (pro)

```python
# 1. Obtenir la probabilité calibrée du modèle
prob_up = calibrator.predict(xgb.predict_proba(features))  # ex: 0.63

# 2. Déterminer quel token acheter
if prob_up > 0.5:
    token_id = token_up
    fair_value = prob_up        # ex: 0.63
else:
    token_id = token_down
    fair_value = 1 - prob_up    # ex: si prob_up=0.38, fair_value_down=0.62

# 3. Regarder l'orderbook réel Polymarket
book = client.get_order_book(token_id)
best_bid = float(book["bids"][0]["price"]) if book["bids"] else 0
best_ask = float(book["asks"][0]["price"]) if book["asks"] else 1
spread = best_ask - best_bid
mid_price = (best_bid + best_ask) / 2

# 4. Calculer le prix d'entrée optimal
min_edge = 0.03  # 3 cents minimum d'edge
entry_price = min(fair_value - min_edge, best_bid + 0.01)

# 5. Filtres de sécurité
if fair_value - entry_price < min_edge:
    skip("Edge insuffisant")
if spread > 0.10:
    skip("Spread trop large, marché illiquide")
if entry_price > 0.55:
    skip("Prix trop élevé, risque/reward mauvais")
if entry_price < 0.25:
    skip("Prix trop bas, probablement pas de fill")
```

### Ordres
- **Type** : Limite GTC avec `postOnly=True` (garantit maker, rebates)
- **Un seul ordre par fenêtre par stratégie**
- **Direction** : acheter le token (UP ou DOWN) où le modèle voit un edge
- **Taille** : déterminée par risk.py (quarter-Kelly)
- **Fallback** : si l'ordre GTC n'est pas fill et qu'on est à T-12s avec confiance > 80%, tenter un FOK à `best_ask` (taker, mais haute conviction)

---

## Stratégie B : Arbitrage Sub-$1

### Principe
Si `prix_YES + prix_NO < 1.00`, acheter les deux → profit garanti au settlement.

### Implémentation
```python
# Vérifier toutes les 2 secondes
book_up = client.get_order_book(token_up)
book_down = client.get_order_book(token_down)

best_ask_up = float(book_up["asks"][0]["price"])
best_ask_down = float(book_down["asks"][0]["price"])
total = best_ask_up + best_ask_down

if total < 0.99:  # 1 cent de marge minimum (pour couvrir les fees taker)
    profit_per_share = 1.00 - total
    # Acheter les deux côtés en FOK simultanément
    size = min(
        float(book_up["asks"][0]["size"]),
        float(book_down["asks"][0]["size"]),
        max_arb_size
    )
    buy_up = client.create_and_post_market_order(...)
    buy_down = client.create_and_post_market_order(...)
    # Profit = profit_per_share * size au settlement
```

### Contraintes
- Nécessite des ordres **market (FOK)** = taker fees
- L'opportunité dure typiquement 2-5 secondes
- Edge de 1-3% par trade, **sans risque directionnel**
- Volume limité par la liquidité disponible
- Vérifier que les DEUX ordres sont fill, sinon on a un risque directionnel

### Gestion du risque arb
- Si un seul côté est fill → on a une position directionnelle non voulue
- Solution : cancel immédiat du côté non-fill, évaluer si on garde la position ou si on la close en market

---

## Risk Management

### Sizing — Stratégie Prédiction (Quarter-Kelly)

```python
def calculate_bet_size(capital, confidence, win_rate_rolling, avg_odds):
    """
    Quarter-Kelly avec protections.
    avg_odds = gain moyen en proportion (ex: 0.55 si on achète à 0.45)
    """
    # Kelly classique pour paris binaires
    p = win_rate_rolling  # ex: 0.57
    b = avg_odds          # ex: (1 - entry_price) / entry_price
    kelly = (p * b - (1 - p)) / b
    kelly = max(kelly, 0)  # Jamais négatif

    # Quarter Kelly (conservateur)
    quarter_kelly = kelly / 4

    # Ajustement par confiance
    bet_fraction = quarter_kelly * confidence

    # Calcul et bornes
    bet_size = capital * bet_fraction
    bet_size = max(2.0, min(bet_size, capital * 0.02, 40.0))

    return bet_size
```

### Sizing — Stratégie Arbitrage
- Taille fixe basée sur la liquidité disponible
- Max 50$ par opportunité d'arb (limité par la profondeur du carnet)
- Pas de Kelly nécessaire (profit garanti si les deux côtés sont fill)

### Protections

| Protection | Seuil | Action |
|---|---|---|
| Confiance minimum (predict) | < 60% | Skip le trade |
| Edge minimum | < 3 cents | Skip le trade |
| Spread maximum | > 10 cents | Skip (marché illiquide) |
| Max bet predict | > 2% bankroll ou > 40$ | Cap la mise |
| Max bet arb | > 50$ | Cap la mise |
| Stop daily | -5% du capital du jour | Stop TOUTE stratégie jusqu'au lendemain |
| Circuit breaker | 5 pertes consécutives (predict) | Pause predict 30 minutes (arb continue) |
| Max drawdown | -15% du capital initial | Arrêt complet, alerte, review manuelle |
| Haute volatilité | Vol réalisée 30min > 2σ historique | Sizing predict divisé par 2 |
| Events macro | FOMC, CPI, NFP, halving | Pas de trade predict ±30 min (arb OK) |
| Modèle dégradé | Brier score glissant > 0.26 | Arrêt predict, retrain auto, reprise si OK |
| Fill rate dégradé | Fill rate < 20% sur 50 derniers ordres | Alerte, ajuster pricing |
| Erreur API | 3 erreurs consécutives | Pause 5 min, retry, alerte si persiste |
| WebSocket déconnecté | Pas de data depuis > 10s | Reconnexion auto, skip fenêtre en cours |

### Anti-adversarial
- **Randomiser** le prix d'entrée de ±0.5 cent pour éviter la détection
- **Randomiser** le timing d'entrée de ±2 secondes dans la fenêtre T-30s à T-25s
- **Ne jamais** placer d'ordres à des prix ronds (0.40, 0.45, 0.50)

---

## Backtest

### Paramètres de simulation réaliste
- **Fill rate** : simulé dynamiquement selon le prix
  - Prix 0.45-0.50 : ~95% fill
  - Prix 0.40-0.45 : ~85% fill
  - Prix 0.35-0.40 : ~65% fill
  - Prix < 0.35 : ~40% fill
- **Fees** : 0 pour maker (rebates), 1.5% pour taker (arb)
- **Latence** : +200ms simulée entre décision et placement
- **Slippage oracle** : ±0.02% random sur le settlement price
- **Données** : 1 mois out-of-sample minimum (jamais vu par le modèle)
- **Capital initial** : paramétrable (default 100$)

### Métriques à tracker

| Métrique | Seuil minimum prod | Description |
|----------|-------------------|-------------|
| Win Rate (top 20% confiance) | > 57% | Accuracy sur les trades haute confiance |
| Profit Factor | > 1.15 | Gross profits / gross losses |
| Sharpe Ratio (annualisé) | > 1.0 | Risk-adjusted return |
| Max Drawdown | < 10% | Pire perte peak-to-trough |
| Brier Score | < 0.24 | Calibration du modèle |
| Fill Rate | > 50% | Proportion d'ordres remplis |
| Trades/jour | 20-80 | Ni trop peu (pas assez de data) ni trop (overfitting à l'action) |
| Calmar Ratio | > 0.5 | Return annualisé / max drawdown |

### Stress tests
- Backtest sur des semaines de haute vol (autour de CPI, FOMC)
- Backtest sur des semaines de basse vol (weekend, fêtes)
- Monte Carlo : 1000 simulations avec resampling des trades pour estimer le percentile 5% du drawdown

---

## Monitoring & Alertes (Production)

### Logging (SQLite)
Chaque trade enregistre :
```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    window_ts INTEGER,
    strategy TEXT,           -- 'predict' ou 'arb'
    direction TEXT,          -- 'UP' ou 'DOWN'
    confidence REAL,
    prob_calibrated REAL,
    entry_price REAL,
    fill_price REAL,
    filled BOOLEAN,
    bet_size REAL,
    result TEXT,             -- 'win', 'loss', 'cancel'
    pnl REAL,
    capital_after REAL,
    brier_score_rolling REAL,
    features_json TEXT,       -- Snapshot des features au moment de la décision
    orderbook_snapshot TEXT,  -- Best bid/ask Polymarket
    binance_price REAL,
    polymarket_rtds_price REAL
);
```

### Alertes Discord/Telegram
- **Chaque heure** : P&L horaire, win rate, nombre de trades, capital
- **Immédiat** : circuit breaker, stop daily, drawdown max, retrain déclenché, erreur API
- **Quotidien** : rapport complet avec toutes les métriques, feature importances, graphe P&L

### Dashboard métriques temps réel
- Brier score glissant (100 trades)
- Win rate glissant (200 trades)
- P&L cumulé
- Fill rate glissant
- Feature importance drift

---

## Dépendances Python

```
# Core
py-clob-client>=0.24      # Polymarket API officielle
python-binance>=1.0        # Binance REST + WebSocket
xgboost>=2.0               # Modèle ML
pandas>=2.0                # Data manipulation
numpy>=1.24                # Calculs numériques
scikit-learn>=1.3          # Métriques, CV, calibration, preprocessing

# Feature engineering
ta>=0.11                   # Indicateurs techniques (RSI, EMA, Bollinger)

# Optimisation
optuna>=3.0                # Bayesian hyperparameter optimization
shap>=0.43                 # Feature importance (SHAP values)

# Storage & Logging
joblib>=1.3                # Sauvegarde modèle

# Alertes
discord-webhook>=1.0       # Alertes Discord
# OU python-telegram-bot   # Alertes Telegram

# Utils
python-dotenv>=1.0         # Variables d'environnement
websockets>=12.0           # WebSocket Polymarket RTDS
schedule>=1.2              # Tâches planifiées (retrain calendaire)
pyarrow>=14.0              # Lecture/écriture Parquet
```

---

## Déploiement (Serveur Irlande)

### Infra
- VPS Linux (Ubuntu 22.04+), 2 CPU, 4GB RAM
- Python 3.11+
- Systemd service pour restart automatique
- NTP synchronisé (< 50ms drift)
- Pas de GPU nécessaire

### Sécurité
- Clés API dans `.env` (jamais dans le code, jamais dans git)
- Wallet Polymarket : clé privée dans variable d'environnement
- `.gitignore` : `.env`, `*.db`, `models/`, `data/`
- Firewall : seul SSH (clé uniquement, pas de password)
- Logs rotatifs (logrotate) pour éviter de remplir le disque
- Monitoring disque/RAM/CPU via simple cron alert

### Service systemd
```ini
[Unit]
Description=Polymarket BTC Bot V3
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/bot
ExecStart=/home/botuser/bot/venv/bin/python bot.py
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/home/botuser/bot/.env

# Limites de sécurité
MemoryMax=2G
CPUQuota=150%

[Install]
WantedBy=multi-user.target
```

### Process de déploiement
```bash
# 1. Setup initial
ssh botuser@ireland-server
git clone <repo> bot && cd bot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configuration
cp .env.example .env
nano .env  # Remplir les clés API

# 3. Entraîner/transférer le modèle
scp models/xgb_model.joblib botuser@server:~/bot/models/
scp models/calibrator.joblib botuser@server:~/bot/models/

# 4. Test
python bot.py --paper  # Paper trading d'abord

# 5. Production
sudo systemctl enable polymarket-bot
sudo systemctl start polymarket-bot
sudo journalctl -u polymarket-bot -f  # Suivre les logs
```

---

## Estimations de performance réalistes

### Win rate attendu (stratégie prédiction)
| Scénario | Win Rate | Trades/jour | ROI mensuel estimé |
|----------|----------|-------------|-------------------|
| Pessimiste | 53-55% | 20-30 | 2-5% |
| Réaliste | 55-58% | 30-50 | 5-15% |
| Optimiste | 58-62% | 40-60 | 15-30% |

### Stratégie arbitrage
- Opportunités : 5-20 par jour (dépend de la liquidité)
- Profit par trade : 1-3% garanti
- Volume limité par la profondeur du carnet ($5-15k par côté)

### Facteurs de risque classés
1. **Fill rate** (risque #1) — si les ordres ne sont pas remplis, pas de profit
2. **Concurrence** — de plus en plus de bots, l'edge se comprime
3. **Changement de règles Polymarket** — fees, structure des marchés
4. **Overfitting** — le backtest peut mentir, seul le paper trading puis le live valident
5. **Oracle divergence** — Chainlink peut setteler différemment de Binance dans les cas limites
