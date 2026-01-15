import azure.functions as func
import json
import logging

app = func.FunctionApp()

@app.route(route="data", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def receive_data(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Received data from microcontroller')
    
    try:
        data = req.get_json()
        logging.info(f'Data: {data}')
        return func.HttpResponse(
            json.dumps({"status": "success", "received": data}),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f'Error: {e}')
        return func.HttpResponse(
            json.dumps({"status": "error", "message": str(e)}),
            status_code=400,
            mimetype="application/json"
        )

@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("OK", status_code=200)