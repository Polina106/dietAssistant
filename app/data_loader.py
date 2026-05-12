import json
import pandas as pd


def load_recipes(path: str):
    # with open(path, 'r', encoding='utf-8') as f:
    #     data = json.load(f)
    data = pd.read_json(path_or_buf=path, lines=True)

    print(pd.DataFrame(data)[:5])
    return pd.DataFrame(data)
