from flask import Flask, request, render_template_string, redirect, url_for, send_file
import csv, io, random
from collections import Counter
from datetime import datetime, timedelta

app = Flask(__name__)

TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Smart Timetable with Times</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; background: #f6f8fa; }
    .card { background: white; padding: 16px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,.08); margin-bottom: 20px; }
    label { display:block; margin-top:8px; font-weight:600; }
    input, textarea { width:100%; padding:8px; margin-top:6px; border-radius:6px; border:1px solid #ccd; }
    button { padding:10px 14px; background:#0b74de; color:white; border:none; border-radius:6px; cursor:pointer; }
    table { border-collapse:collapse; width:100%; margin-top:12px; }
    th, td { border:1px solid #ddd; padding:8px; text-align:center; }
    th { background:#0b74de; color:white; }
    .break { background:#fff4d6; font-style:italic; }
    .small { font-size:0.85em; color:#555; }
    .controls { display:flex; gap:10px; margin-top:10px; }
    .error { color:crimson; font-weight:700; }
  </style>
</head>
<body>
  <h1>Smart Timetable with Real Times</h1>

  <div class="card">
    <form method="post" action="/">
      <label>Subjects (Name,Count per week)</label>
      <textarea name="subjects" rows="6" placeholder="Math,5
English,5
Science,4"></textarea>

      <label>Days (comma separated)</label>
      <input name="days" value="Monday,Tuesday,Wednesday,Thursday,Friday">

      <label>Number of periods per day</label>
      <input name="periods" value="8">

      <label>Start time of school (HH:MM)</label>
      <input name="start_time" value="09:00">

      <label>End time of school (HH:MM)</label>
      <input name="end_time" value="16:00">

      <label>Short break after which period?</label>
      <input name="short_break_after" value="2">

      <label>Short break length (minutes)</label>
      <input name="short_break_length" value="15">

      <label>Lunch break after which period?</label>
      <input name="lunch_after" value="4">

      <label>Lunch break length (minutes)</label>
      <input name="lunch_length" value="30">

      <div class="controls">
        <button type="submit">Generate Timetable</button>
      </div>
    </form>
  </div>

  {% if error %}
    <div class="card error">{{ error }}</div>
  {% endif %}

  {% if grid %}
    <div class="card">
      <h2>Generated Timetable</h2>
      <table>
        <thead>
          <tr>
            <th>Day / Period</th>
            {% for p in range(1, periods+1) %}
              <th>P{{p}}<br><span class="small">{{ times_map[p] }}</span></th>
            {% endfor %}
          </tr>
        </thead>
        <tbody>
          {% for day in days_list %}
            <tr>
              <td style="font-weight:700;">{{ day }}</td>
              {% for p in range(1, periods+1) %}
                {% set slot = grid[day][p-1] %}
                {% if slot is none %}
                  <td>-</td>
                {% elif slot.break %}
                  <td class="break">{{ slot.name }}</td>
                {% else %}
                  <td>{{ slot.subject }}</td>
                {% endif %}
              {% endfor %}
            </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  {% endif %}
</body>
</html>
"""

# ---------------------------
# Simple Scheduler
# ---------------------------
def parse_subjects_text(text):
    out = {}
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if ',' in s:
            name, cnt = s.split(',', 1)
            out[name.strip()] = out.get(name.strip(), 0) + int(cnt.strip())
    return out

def build_initial_slots(days, periods_per_day, lunch_after, short_break_after):
    slots = {}
    for d in days:
        row = []
        for p in range(1, periods_per_day + 1):
            if lunch_after and p == lunch_after:
                row.append({'break': True, 'name': 'Lunch'})
            elif short_break_after and p == short_break_after:
                row.append({'break': True, 'name': 'Break'})
            else:
                row.append(None)
        slots[d] = row
    return slots

def subject_counts_to_list(subject_counts):
    lst = []
    for name, cnt in subject_counts.items():
        lst.extend([name] * cnt)
    return lst

def schedule_agent(days, periods_per_day, lunch_after, short_break_after, subject_counts):
    subjects_list = subject_counts_to_list(subject_counts)
    grid = build_initial_slots(days, periods_per_day, lunch_after, short_break_after)

    remaining = dict(subject_counts)
    for subj in subjects_list:
        # pick a random free slot (ignores back-to-back constraint for simplicity)
        placed = False
        random.shuffle(days)
        for d in days:
            for p in range(1, periods_per_day+1):
                if grid[d][p-1] is None:
                    grid[d][p-1] = {'subject': subj}
                    placed = True
                    break
            if placed:
                break
    return grid

def build_times_map(start_time, end_time, periods, lunch_after, lunch_length, short_break_after, short_break_length):
    start = datetime.strptime(start_time, "%H:%M")
    end = datetime.strptime(end_time, "%H:%M")
    total_minutes = int((end - start).total_seconds() // 60)

    # remove break minutes
    active_minutes = total_minutes - lunch_length - short_break_length
    period_len = active_minutes // periods

    times_map = {}
    current = start
    for p in range(1, periods+1):
        slot_len = period_len
        if p == short_break_after:
            endt = current + timedelta(minutes=short_break_length)
            times_map[p] = f"{current.strftime('%H:%M')} - {endt.strftime('%H:%M')} (Break)"
            current = endt
        elif p == lunch_after:
            endt = current + timedelta(minutes=lunch_length)
            times_map[p] = f"{current.strftime('%H:%M')} - {endt.strftime('%H:%M')} (Lunch)"
            current = endt
        else:
            endt = current + timedelta(minutes=period_len)
            times_map[p] = f"{current.strftime('%H:%M')} - {endt.strftime('%H:%M')}"
            current = endt
    return times_map

# ---------------------------
# Flask routes
# ---------------------------
@app.route("/", methods=["GET","POST"])
def index():
    error = None
    grid = None
    days_list = []
    periods = 0
    times_map = {}
    if request.method == "POST":
        try:
            sub_text = request.form.get("subjects","")
            days_raw = request.form.get("days","Monday,Tuesday,Wednesday,Thursday,Friday")
            periods = int(request.form.get("periods","8"))
            start_time = request.form.get("start_time","09:00")
            end_time = request.form.get("end_time","16:00")
            lunch_after = int(request.form.get("lunch_after","4"))
            lunch_length = int(request.form.get("lunch_length","30"))
            short_break_after = int(request.form.get("short_break_after","2"))
            short_break_length = int(request.form.get("short_break_length","15"))

            subject_counts = parse_subjects_text(sub_text)
            days_list = [d.strip() for d in days_raw.split(",") if d.strip()]

            grid = schedule_agent(days_list, periods, lunch_after, short_break_after, subject_counts)
            times_map = build_times_map(start_time, end_time, periods, lunch_after, lunch_length, short_break_after, short_break_length)
        except Exception as e:
            error = str(e)

    return render_template_string(TEMPLATE, error=error, grid=grid, days_list=days_list, periods=periods, times_map=times_map)

if __name__ == "__main__":
    app.run(debug=True)
