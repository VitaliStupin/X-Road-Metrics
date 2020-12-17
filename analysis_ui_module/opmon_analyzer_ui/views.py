import datetime
import json
from bson import ObjectId

from django.shortcuts import render
from django.http import HttpResponse, HttpResponseNotFound, HttpResponseServerError
from django.template.defaulttags import register
from django.views.decorators.csrf import ensure_csrf_cookie
import numpy as np

from .settings_parser import OpmonSettingsManager
from .db_manager import IncidentDatabaseManager
from .logger_manager import LoggerManager
from . import constants


def index(request, profile=None):
    try:
        settings = _get_settings(profile)
    except (FileNotFoundError, PermissionError):
        return HttpResponseNotFound("Settings profile not found.")
    logger = _get_logger(settings)
    logger.log_info("_process_incident_data_request", "Fetching incident data.")
    return render(
        request, "gui/index.html",
        context={'xroad_instance': settings['xroad']['instance'], 'settings_profile': profile}
    )


@ensure_csrf_cookie
def get_incident_data_serverside(request, profile=None):
    data = _process_incident_data_request(request,
                                          profile,
                                          incident_status=["new", "showed"],
                                          relevant_cols=constants.new_incident_columns,
                                          update_status_shown=True)
    if "error_message" in data:
        return HttpResponseNotFound(data["error_message"])
    
    return HttpResponse(json.dumps(data))


@ensure_csrf_cookie
def get_historic_incident_data_serverside(request, profile=None):
    data = _process_incident_data_request(request,
                                          profile,
                                          incident_status=["normal", "incident", "viewed"],
                                          relevant_cols=constants.historical_incident_columns,
                                          update_status_shown=False)
    
    if "error_message" in data:
        return HttpResponseNotFound(data["error_message"])
    
    return HttpResponse(json.dumps(data))


def _process_incident_data_request(request, profile, incident_status, relevant_cols, update_status_shown):
    settings = _get_settings(profile)
    logger = _get_logger(settings)
    logger.log_info("_process_incident_data_request", "Fetching incident data.")
    db_manager = IncidentDatabaseManager(settings)
    order_col = int(request.POST["order[0][column]"])
    order_col_name = request.POST["columns[%s][name]" % order_col]
    if order_col_name in ["service_call", "mark_as", "actions"]:
        order_col_name = "clientMemberCode"
        
    start_time = datetime.datetime.now() - datetime.timedelta(minutes=constants.incident_expiration_time)
    incident_data = db_manager.load_incident_data(start=int(request.POST["start"]),
                                                  length=int(request.POST["length"]),
                                                  order_col_name=order_col_name,
                                                  order_col_dir=request.POST["order[0][dir]"],
                                                  incident_status=incident_status,
                                                  start_time=start_time,
                                                  filter_constraints=json.loads(request.POST["filterConstraints"]))
    
    if "error_message" in incident_data:
        return incident_data
    
    if update_status_shown:
        # change the status of all incidents that will be shown now in table to "showed"
        db_manager.update_incidents(ids=[incident["_id"] for incident in incident_data["data"]],
                                    field="incident_status",
                                    value="showed")
    
    # generate data list, taking relevant fields from each incident
    incident_data_list = []
    for incident in incident_data["data"]:

        # add concatenated service call
        incident_data_dict = {"0": " ".join([incident[field] for field in constants.service_call_fields])}
        
        # add relevant fields
        for idx, (col_name, field, data_type, round_prec, date_format) in enumerate(relevant_cols):
            if round_prec is not None:
                incident_data_dict[str(idx + 1)] = np.round(float(incident[field]), round_prec)
            elif date_format is not None:
                incident_data_dict[str(idx + 1)] = incident[field].strftime(date_format)
            else:
                incident_data_dict[str(idx + 1)] = str(incident[field])
                
        # add incident id
        incident_data_dict["DT_RowId"] = str(incident["_id"])
            
        incident_data_list.append(incident_data_dict)
    
    data = {"draw": int(request.POST["draw"]),
            "recordsTotal": incident_data["total_count"],
            "recordsFiltered": incident_data["filtered_count"],
            "data": incident_data_list}
    
    return data


def get_incident_table_initialization_data(request, profile=None):
    settings = _get_settings(profile)
    logger = _get_logger(settings)
    logger.log_info("get_incident_table_initialization_data", "Initializing incident table view.")
    db_manager = IncidentDatabaseManager(settings)
    
    table_id = json.loads(request.GET["table_id"])
    
    n_service_call_field_cols = len(constants.service_call_fields) + 1
    
    # create column names data
    if table_id == "#incident_table":
        relevant_cols = constants.new_incident_columns
        order = constants.new_incident_order
        incident_status = ["new", "showed"]
    else:
        relevant_cols = constants.historical_incident_columns
        order = constants.historical_incident_order
        incident_status = ["normal", "incident", "viewed"]
    
    cols = [{"name": "service_call", "title": "Service call", "data_type": "categorical"}]
    cols += [{"name": field, "title": col_name, "data_type": data_type} for col_name, field, data_type, _, _ in relevant_cols]
    cols += [{"name": "actions", "title": "Actions"},
             {"name": "mark_as", "title": "Mark as"}]
    
    anomaly_type_idx = [i for i in range(len(cols)) if cols[i]["name"] == "anomalous_metric"]
    anomaly_type_idx = anomaly_type_idx[0] if len(anomaly_type_idx) > 0 else 0
    comment_field_idx = [i for i in range(len(cols)) if cols[i]["name"] == "comments"]
    comment_field_idx = comment_field_idx[0] if len(comment_field_idx) > 0 else 0
    
    # create column order data
    idx_order = []
    col_names = [d["name"] for d in cols]
    for field, direction in order:
        field_idx = col_names.index(field)
        idx_order.append([field_idx, direction])
    
    html_header = "\n".join(["<th>%s</th>" % col["title"] for col in cols])
    html = """<thead>
                <tr>
                  <th colspan="%s">%s</th>
                  <th colspan="%s">Incident</th>
                </tr>
                <tr>
                  %s
                </tr>
              </thead>
              <tfoot>
                <tr>
                  %s
                </tr>
              </tfoot>
            """ % (n_service_call_field_cols, cols[0]["title"],
                   len(cols) - n_service_call_field_cols,
                   html_header,
                   html_header)
    
    start_time = datetime.datetime.now() - datetime.timedelta(minutes=constants.incident_expiration_time)
    filter_selector_html = []
    for _, field, data_type, _, _ in relevant_cols:
        if data_type == 'categorical':
            distinct_values = db_manager.get_distinct_values(field, start_time=start_time, incident_status=incident_status)
        else:
            distinct_values = ""
        filter_selector_html.append(
            '<option value="%s" data-type="%s" data-distinct_values="%s">%s</option>' % (field, data_type,
                                                                                         ",".join(distinct_values), field))
    filter_selector_html = "\n".join(filter_selector_html)
    
    data = {"columns": cols,
            "html": html,
            "order": idx_order,
            "service_call_field_idxs": list(range(1, n_service_call_field_cols)),
            "filter_selector_html": filter_selector_html,
            "historic_averages_anomaly_types": constants.historic_averages_anomaly_types,
            "anomaly_type_idx": anomaly_type_idx,
            "comment_field_idx": comment_field_idx}
                                            
    return HttpResponse(json.dumps(data))


def get_request_list(request, profile=None):
    settings = _get_settings(profile)
    logger = _get_logger(settings)
    db_manager = IncidentDatabaseManager(settings)

    incident_id = json.loads(request.GET["incident_id"])
    logger.log_info("get_request_list", f"Getting request list for incident {incident_id}.")
    requests = db_manager.get_request_list(ObjectId(incident_id), limit=constants.example_request_limit)

    requests_relevant_data = []
    for req in requests:
        # extract nested fields
        if req["client"] is not None:
            current_request_relevant_data = [req["client"][col] for col in
                                             constants.relevant_fields_for_example_requests_nested]
        else:
            current_request_relevant_data = [req["producer"][col] for col in
                                             constants.relevant_fields_for_example_requests_nested]
        # extract alternative fields
        current_request_relevant_data += [req[f1] if req[f1] is not None else req[f2]
                                          for _, f1, f2 in constants.relevant_fields_for_example_requests_alternative]
                                          
        # extract general fields
        current_request_relevant_data += [req[col] for col in
                                          constants.relevant_fields_for_example_requests_general]
        
        requests_relevant_data.append(current_request_relevant_data)
            
    relevant_cols = (constants.relevant_fields_for_example_requests_nested +
                     [col for col, _, _ in constants.relevant_fields_for_example_requests_alternative] +
                     constants.relevant_fields_for_example_requests_general)
    data = {"requests": requests_relevant_data, "columns": [{"title": col} for col in relevant_cols]}
    return HttpResponse(json.dumps(data))


@ensure_csrf_cookie
def update_incident_status(request, profile=None):
    settings = _get_settings(profile)
    logger = _get_logger(settings)
    logger.log_info("update_incident_status", "Incident status update started.")
    if request.is_ajax():
        n_updated_status = 0
        n_updated_comments = 0
        db_manager = IncidentDatabaseManager(settings)

        for status in ['normal', 'incident', 'viewed']:
            ids = [ObjectId(val) for val in json.loads(request.POST[status])]
            n_updated_status += db_manager.update_incidents(ids=ids, field="incident_status", value=status)
            
        updated_comment_ids = json.loads(request.POST["updated_comment_ids"])
        updated_comments = json.loads(request.POST["updated_comments"])
        for idd, comment in zip(updated_comment_ids, updated_comments):
            n_updated_comments += db_manager.update_incidents(ids=[ObjectId(idd)], field="comments", value=comment)

        message = f"Successfully updated {n_updated_status} incident status and {n_updated_comments} incident comments."
        logger.log_info('analyzer_interface', message)
    else:
        message = "Not Ajax"
    return HttpResponse(message)


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def get_type(value):
    return type(value).__name__


@register.filter
def get_id(value):
    return value['_id']


def _get_settings(profile=None):
    if profile == "":
        profile = None
    return OpmonSettingsManager(profile).settings


def _get_logger(settings):
    return LoggerManager(settings['logger'], settings['xroad']['instance'])
