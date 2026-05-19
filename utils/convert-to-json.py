import pandas as pd
import json
import os

# Paths are relative to HeathCareAI-Backend/ (the intended working directory).
# Run with:  cd HeathCareAI-Backend && python tests/convert-to-json.py
INPUT_CSV = 'data/PatientData/NutritionDataSetxlsx.xlsx'
OUTPUT_FOLDER = 'data/PatientData/Patient_JSON_Records'


def convert_to_json(csv_file_path=INPUT_CSV, output_directory=OUTPUT_FOLDER):
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
        print(f"Created directory: {output_directory}")

    try:
        if csv_file_path.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(csv_file_path)
        else:
            df = pd.read_csv(csv_file_path)
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    count = 0
    for index, row in df.iterrows():
        record = row.to_dict()

        patient_id = str(record.get('Patient_ID', f"unknown_patient_{index}"))

        clean_filename = "".join(
            [c for c in patient_id if c.isalnum() or c in (' ', '.', '-', '_')]
        ).strip()
        file_path = os.path.join(output_directory, f"{clean_filename}.json")

        with open(file_path, 'w', encoding='utf-8') as json_file:
            json.dump(record, json_file, indent=4, ensure_ascii=False)

        count += 1

    print(f"Success! {count} JSON files have been created in the '{output_directory}' folder.")


if __name__ == "__main__":
    convert_to_json()
