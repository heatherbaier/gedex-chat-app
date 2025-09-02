from flask import Flask, request, jsonify, render_template, session
from openai import OpenAI
import json
import os
import psycopg2
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.utils  # ✅ Needed for JSON encoding


with open("./config.json", "r") as f:
    config = json.load(f)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "super-secret-key")

client = OpenAI(api_key=config["openaiapikey"])

DB_CONFIG = {
    'dbname': config["dbname"],
    'user': config["user"],
    'password': config["password"],
    'host': config["host"],
    'port': config["port"]
}

@app.route('/')
def index():
    return render_template('index.html')


with open("./schema_context.txt", "r") as f:
    global schema_context
    schema_context = f.read()


@app.route('/chat', methods=['POST'])

def chat():
    user_message = request.json['message']

    print("User Message: ", user_message)

    if 'history' not in session:
        session['history'] = []
        session['current_country'] = None
        session['current_school'] = None
        session['confirmed_adm1'] = None
        session['confirmed_adm2'] = None

    lowered = user_message.lower()
    for iso in ['phl', 'khm', 'hnd', 'lby']:
        if iso in lowered or any(country in lowered for country in ['philippines', 'cambodia', 'honduras', 'libya']):
            session['current_country'] = iso.upper()
            break

    memory_hint = ""
    if session.get("current_country") or session.get("current_school"):
        memory_hint += "\n\nCurrent query context:\n"
        if session.get("current_country"):
            memory_hint += f"- Country: {session['current_country']}\n"
        if session.get("current_school"):
            memory_hint += f"- School: {session['current_school']}\n"
        memory_hint += "If this context differs from the previous message, please ignore earlier schools or countries and respond based on the most recent user message."

    full_context = schema_context + memory_hint
    session['history'].insert(0, {"role": "system", "content": full_context})
    session['history'].append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=session['history'],
        temperature=0.2
    )

    assistant_message = response.choices[0].message.content
    sql_code = extract_sql_from_response(assistant_message)

    result_table_html = None
    plotData = None

    # === HANDLE SIMILARITY QUERY CASES ===
    if sql_code and "similarity(" in sql_code.lower():
        try:
            df = run_sql_query(sql_code)

            if df.empty:
                assistant_message += "\n\n⚠️ The query ran but returned no results."
            else:
                # Auto-confirm top result
                top_school = df.iloc[0]
                session["current_school"] = top_school["school_name"]
                session["confirmed_adm1"] = top_school.get("adm1")
                session["confirmed_adm2"] = top_school.get("adm2")

                assistant_message += f"\n\n✅ Automatically selected: **{top_school['school_name']}** in {top_school.get('adm1')}, {top_school.get('adm2')}."
                # result_table_html = df.to_html(classes='table table-hover')

                df['Confirm'] = df.apply(
                    lambda row: (
                        f"<button class='btn btn-sm btn-primary' "
                        f"onclick=\"confirmSchool('{row['school_name']}', '{row['adm1']}', '{row['adm2']}')\">"
                        f"Confirm</button>"
                    ), axis=1
                )

                result_table_html = df.to_html(classes='table table-hover', escape=False, index=False)


                # Force GPT to regenerate based on confirmed school
                return jsonify({
                    "response": assistant_message + "\n\n🔄 Reprocessing request with confirmed school...",
                    "table": result_table_html,
                    "plotData": None,
                    "retry": True,
                    "forced_query": f"Generate a school report card for {top_school['school_name']} in {top_school.get('adm1')}, {top_school.get('adm2')}."
                })

        except Exception as e:
            assistant_message += f"\n\n⚠️ Error running similarity match:\n```\n{e}\n```"
        return jsonify({
            "response": assistant_message,
            "table": result_table_html,
            "plotData": None,
        })

    # === STANDARD SQL HANDLING ===
    if sql_code:
        try:
            df = run_sql_query(sql_code)

            if df.empty:
                assistant_message += "\n\n⚠️ The query ran but returned no results."
            else:
                result_table_html = df.to_html(classes='table table-striped')
                plotData = auto_generate_chart(df)
        except Exception as e:
            assistant_message += f"\n\n⚠️ Error executing SQL:\n```\n{e}\n```"

    # Save only now that we've passed similarity loop
    session['history'].append({"role": "assistant", "content": assistant_message})

    return jsonify({
        "response": assistant_message,
        "table": result_table_html,
        "plotData": plotData,
    })

@app.route('/reset', methods=['POST'])
def reset():
    session.pop('history', None)
    session.pop('current_country', None)
    session.pop('current_school', None)
    return jsonify({"status": "reset"})

def extract_sql_from_response(text):
    if "```sql" in text:
        return text.split("```sql")[-1].split("```")[0].strip()
    return None

def run_sql_query(query):
    with psycopg2.connect(**DB_CONFIG) as conn:
        return pd.read_sql(query, conn)

def auto_generate_chart(df):

    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

    print(df)

    if 'adm1' in df.columns and len(numeric_cols) == 1:
        categories = df['adm1'].tolist()
        series_data = df[numeric_cols[0]].tolist()
        return {
            "categories": categories,
            "series": [{"name": numeric_cols[0], "data": series_data}]
        }

    elif 'adm1' in df.columns and set(['total_male_students', 'total_female_students']).issubset(df.columns):

        print("TRIGGERED")
        
        categories = df['adm1'].tolist()
        male_data = df['total_male_students'].tolist()
        female_data = df['total_female_students'].tolist()
        return {
            "categories": categories,
            "series": [
                {"name": "Male", "data": male_data},
                {"name": "Female", "data": female_data}
            ]
        }

    return None

if __name__ == '__main__':
    app.run(debug=True)
