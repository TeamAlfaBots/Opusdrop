from fastapi.responses import JSONResponse

def error(status:int, code:str, message:str, detail=None):
    body={'error':{'code':code,'message':message}}
    if detail is not None: body['error']['detail']=detail
    return JSONResponse(body,status_code=status)
