import inspect, os, sys
import numpy as np, pandas as pd, torch
sys.path.insert(0, os.environ.get("KRONOS_SRC", "/home/ubuntu/kronos_research/Kronos"))
import model.kronos as K
from model import Kronos, KronosTokenizer

_src = inspect.getsource(K.auto_regressive_inference)
_target = "preds = np.mean(preds, axis=1)"
assert _src.count(_target) == 1
_ns = dict(K.__dict__)
exec(_src.replace("def auto_regressive_inference", "def ar_paths").replace(_target, "pass"), _ns)
ar_paths = _ns["ar_paths"]

PRICE = ["open", "high", "low", "close"]
COLS = PRICE + ["volume", "amount"]

class Sampler:
    def __init__(self, name, max_context=512, clip=5):
        self.tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base").eval()
        self.model = Kronos.from_pretrained(f"NeoQuasar/{name}").eval()
        self.max_context, self.clip = max_context, clip

    def paths(self, df, x_ts, y_ts, n_samples, T=1.0, top_p=0.9, seed=0):
        """df: OHLCV(+amount) history ending at cutoff; returns array (n_samples, pred_len, 6) in price units."""
        df = df.copy()
        mid = df[PRICE].mean(axis=1)
        if df["volume"].isna().all() and "amount" in df and df["amount"].notna().all():
            df["volume"] = df["amount"] / mid  # some index files only carry turnover
        df["amount"] = df["volume"] * mid  # same derivation for indices and stocks
        x = df[COLS].values.astype(np.float32)
        assert not np.isnan(x).any()
        mu, sd = x.mean(0), x.std(0)
        xn = np.clip((x - mu) / (sd + 1e-5), -self.clip, self.clip)
        xs = K.calc_time_stamps(pd.Series(pd.to_datetime(x_ts))).values.astype(np.float32)
        ys = K.calc_time_stamps(pd.Series(pd.to_datetime(y_ts))).values.astype(np.float32)
        torch.manual_seed(seed)
        z = ar_paths(self.tok, self.model, torch.from_numpy(xn[None]), torch.from_numpy(xs[None]),
                     torch.from_numpy(ys[None]), self.max_context, len(y_ts), self.clip, T, 0, top_p, n_samples, False)
        z = z[0, :, -len(y_ts):, :]  # (samples, pred_len, 6)
        return z * (sd + 1e-5) + mu
