import plotly.express as px
import pandas as pd
import plotly.utils  # ✅ Needed for JSON encoding
import json
import plotly


x = ["what", "is", "up"]
y = [1,7,3]

df = pd.DataFrame()
df["x"] = x
df["y"] = y

fig = px.bar(df, x='x', y='y', text='y')


fig_json = json.loads(json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder))


fig_json2 = json.loads(fig.to_json())

print("Readable Plot Data:")
print(json.dumps(fig_json2['data'], indent=2))