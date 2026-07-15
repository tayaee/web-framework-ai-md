# Temperature Conversion Microservice API

## Routing Rules
- Create a 'POST /v1/convert' endpoint.
- Input Rule (JSON): {"input_temperature": 30, "input_unit": "C"} (type must be C or F)

## Business Logic
- If input_unit is "C", convert Celsius to Fahrenheit and return.
- If input_unit is "F", convert Fahrenheit to Celsius and return.
- Output Rule (JSON): {"output_temperature": converted_value, "output_unit": "F"}
