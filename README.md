# IADAI2021000465-Nihith Ram Bikkina

# Candidate Name - Nihith Ram Bikkina

# Candidate Registration Number - 1000465

# CRS Name: Artificial Intelligence

# Course Name - Mathematics for Artificial Intelligence

# School name - Birla Open Minds International School, Kollur

# Summative Assessment

# Player Injuries and Team Performance Dashboard 

## Live app: https://hdjpiqqmnygm75gqpgex5l.streamlit.app/ 


## Project Overview

When a key player gets injured, managers usually feel the team gets worse, but how much worse, and for which injuries? This Streamlit dashboard was built for the FootLens Analytics scenario to put numbers on that question.

The dataset has one row per injury. For each one it records the player (club, position, age, FIFA rating), the injury type, the dates the player went out and came back, and the result, goal difference and player rating for the three matches before the injury, the three matches missed and the three matches after the return. That structure makes it possible to compare the same team and player across the three phases. The raw data was cleaned and extended with new columns, then turned into an interactive dashboard that helps managers and analysts make decisions on training schedules, player rotation and squad planning.

## What the Dashboard Analyses

The dashboard looks at which injuries hurt the team most, how results change before, during and after a player's absence, whether players return as good as before, when and where injuries cluster across clubs and months, which clubs lose the most to injuries, and whether player age relates to the size of the performance drop.

## Key Features

- Six interactive Plotly visuals (hover, zoom, switch options): a bar chart of the top injuries by team performance drop, a win/draw/loss stacked bar chart, a player timeline line chart, a club-by-month heatmap, an age vs performance drop scatter plot with a trend line, and a comeback leaderboard table
- Sidebar filters for season, club, position, injury category and age that update every chart instantly
- Automatic data cleaning with new columns such as average rating before and after, rating change, and a team performance drop index
- Statistical analysis: a paired t-test on before vs after ratings, correlation and a trend line for age vs drop, and pivot tables comparing pre- and post-injury performance
- A short plain-English takeaway under each chart
- A "Data & Cleaning" tab showing exactly what was cleaned, plus a button to download the cleaned dataset

## How the Data Was Prepared

- Renamed the long raw column names (for example, Match1_before_injury_Player_rating became before_1_rating).
- Turned placeholders like "N.A." and blanks into real missing values.
- Converted the injury and return dates to dates and worked out how many days each injury lasted.
- Dropped duplicate rows, unreadable dates and injuries that ended before they started.
- Filled missing age and FIFA rating with the median. Missing match ratings were not filled in; they are skipped when averages are calculated so no values are made up.

Columns created:

- **injury_days:** days out
- **avg_rating_before, avg_rating_after and rating_change:** the player's form around the injury
- **performance_drop_index:** the team's average goal difference before the injury minus during the absence. A positive number means the team did worse without the player.
- **ppg_before, ppg_during, ppg_after:** team points per game (win 3, draw 1, loss 0)

The data was also grouped by player to summarise the before, during and after phases.

## Integration Details

Everything lives in app.py, in three parts that feed each other: the raw CSV in the data folder is cleaned and extended with new columns using pandas, the analysis functions then summarise it (groupby, pivot tables and SciPy statistics), and finally Streamlit and Plotly display the results as an interactive dashboard. The cleaning result is cached with st.cache_data, so it runs once and the filters stay fast.

## Deployment Instructions

To run it on your own machine, install the packages listed in requirements.txt and start the app with Streamlit using app.py as the main file.

To deploy on Streamlit Community Cloud:

1. Put app.py, requirements.txt and the data folder in a public GitHub repository.
2. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub and choose **Create app**.
3. Pick the repository, the main branch and app.py as the main file, then click **Deploy**.

## Screenshots

<img width="300" height="904" alt="image" src="https://github.com/user-attachments/assets/a34aa240-31c3-4316-a82b-4ca8b323ff62" />
<img width="1281" height="942" alt="image" src="https://github.com/user-attachments/assets/e1d0e6de-32c7-4c27-8a29-51443868ceeb" />
<img width="1274" height="994" alt="image" src="https://github.com/user-attachments/assets/437cafc1-5454-456e-8fa4-08654039cf6f" />
<img width="1306" height="915" alt="image" src="https://github.com/user-attachments/assets/1b4652b8-abc8-487e-8785-baa8ac4fdea5" />
<img width="1291" height="920" alt="image" src="https://github.com/user-attachments/assets/9d4d36e8-f76f-40b9-a443-30bbaad5158d" />
<img width="1313" height="950" alt="image" src="https://github.com/user-attachments/assets/0b14858a-b47f-4905-8fb2-f971788db913" />
<img width="1307" height="927" alt="image" src="https://github.com/user-attachments/assets/b7456a45-8cb8-4713-bacf-af27bd850705" />
<img width="1303" height="910" alt="image" src="https://github.com/user-attachments/assets/913e396d-8858-460a-b5c5-664989b25010" />
<img width="1327" height="994" alt="image" src="https://github.com/user-attachments/assets/19708949-7311-4a72-acb4-a09806300098" />
<img width="1250" height="838" alt="image" src="https://github.com/user-attachments/assets/d6862bd8-5561-43f3-8366-8a47c5c7e40d" />

## Repository Structure

```
.
├── data/
│   └── <your_dataset>.csv          # Raw dataset the app reads
├── notebooks/
│   └── Football_Injuries_Preprocessing_and_Analysis.ipynb   # Colab cleaning and analysis
├── screenshots/
│   ├── dashboard_preview.png
│   ├── injury_impact.png
│   ├── player_timeline.png
│   ├── injury_clusters.png
│   ├── age_vs_drop.png
│   └── comebacks.png
├── app.py                          # Cleaning, analysis and Streamlit dashboard
├── requirements.txt                # Python packages needed
└── README.md                       # Project documentation
```
