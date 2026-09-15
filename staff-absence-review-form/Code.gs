const SHEET_ID_PROPERTY = 'ABSENCE_SUBMISSION_SHEET_ID';
const APPROVERS_PROPERTY = 'APPROVER_EMAILS';
const GLOBAL_APPROVERS_PROPERTY = 'GLOBAL_APPROVER_EMAILS';
const WORKSHEET_NAME = 'Absence Requests';
const REQUIRED_HEADERS = [
  'submission_uuid','submitted_at','staff_email','absence_type','duration_mode','start_date','end_date',
  'start_time','days_value','notes','processing_status','processing_started_at','processed_at',
  'launchpad_request_id','processing_error','processing_attempts','last_processing_attempt_at',
  'processing_claim_id','staff_display_name','department_name','approval_manager_email','workflow_status','reviewed_by','reviewed_at',
  'decision_note','launchpad_sync_status','launchpad_synced_at','launchpad_sync_error','decision_claim_id'
];
const DURATION_LABELS = {
  quarter_day:'2 hours', half_day:'4 hours', three_quarter_day:'6 hours',
  full_day:'8 hours / Full regular day', summer_2_hours:'Summer - 2 hours',
  summer_4_hours:'Summer - 4 hours', summer_6_hours:'Summer - 6 hours',
  summer_8_hours:'Summer - 8 hours', summer_full_day:'Summer full day - 10 hours / 1.25 days',
  multi_day:'Multiple Days'
};

function doGet(event) {
  const id = event && event.parameter ? event.parameter.id : '';
  try {
    getReviewRequest(id);
    const template = HtmlService.createTemplateFromFile('Review');
    template.requestId = id;
    return template.evaluate().setTitle('Review Absence Request')
      .addMetaTag('viewport','width=device-width, initial-scale=1');
  } catch (error) {
    console.warn('Review access denied: %s', error && error.message ? error.message : 'unknown');
    return HtmlService.createHtmlOutputFromFile('AccessDenied').setTitle('Access Denied')
      .addMetaTag('viewport','width=device-width, initial-scale=1');
  }
}

function getReviewRequest(submissionUuid) {
  const request = findRequest_(normalizeUuid_(submissionUuid));
  if (!request) throw new Error('Request not found.');
  return response_(request.values, authorize_(request.values));
}

function submitReviewDecision(submissionUuid, decision, decisionNote) {
  const id = normalizeUuid_(submissionUuid);
  const action = String(decision || '').trim().toLowerCase();
  if (['approved','denied'].indexOf(action) === -1) throw new Error('Choose Approve or Deny.');
  const note = String(decisionNote || '').trim();
  if (note.length > 1000) throw new Error('Decision note cannot exceed 1000 characters.');
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const request = findRequest_(id);
    if (!request) throw new Error('Request not found.');
    const reviewer = authorize_(request.values);
    if (String(request.values.workflow_status || 'pending').toLowerCase() !== 'pending') {
      return response_(request.values, reviewer);
    }
    update_(request.sheet, request.rowNumber, request.headers, {
      workflow_status:action, reviewed_by:reviewer, reviewed_at:new Date().toISOString(),
      decision_note:note, launchpad_sync_status:'pending', launchpad_synced_at:'',
      launchpad_sync_error:'', decision_claim_id:''
    });
    SpreadsheetApp.flush();
    return response_(findRequest_(id).values, reviewer);
  } finally { lock.releaseLock(); }
}

function normalizeUuid_(value) {
  const id = String(value || '').trim().toLowerCase();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id)) {
    throw new Error('Request not found.');
  }
  return id;
}

function emailList_(name) {
  return String(PropertiesService.getScriptProperties().getProperty(name) || '').split(',')
    .map(function(value){return value.trim().toLowerCase();}).filter(function(value){return !!value;});
}

function authorize_(row) {
  const email = String(Session.getActiveUser().getEmail() || '').trim().toLowerCase();
  if (!email) throw new Error('Google could not verify your signed-in account.');
  const approvers = emailList_(APPROVERS_PROPERTY);
  const globals = emailList_(GLOBAL_APPROVERS_PROPERTY);
  if (approvers.indexOf(email) === -1 && globals.indexOf(email) === -1) throw new Error('This account is not authorized.');
  if (globals.indexOf(email) === -1 && email !== String(row.approval_manager_email || '').trim().toLowerCase()) {
    throw new Error('This request is assigned to another reviewer.');
  }
  return email;
}

function queue_() {
  const id = String(PropertiesService.getScriptProperties().getProperty(SHEET_ID_PROPERTY) || '').trim();
  if (!id) throw new Error('Review service is not configured.');
  const sheet = SpreadsheetApp.openById(id).getSheetByName(WORKSHEET_NAME);
  if (!sheet || sheet.getLastRow() < 1) throw new Error('Review service is not configured.');
  const headers = sheet.getRange(1,1,1,sheet.getLastColumn()).getDisplayValues()[0]
    .map(function(value){return String(value || '').trim();});
  if (REQUIRED_HEADERS.some(function(header){return headers.indexOf(header) === -1;})) {
    throw new Error('Review service is not configured.');
  }
  return {sheet:sheet,headers:headers};
}

function findRequest_(id) {
  const queue = queue_();
  if (queue.sheet.getLastRow() < 2) return null;
  const column = queue.headers.indexOf('submission_uuid') + 1;
  const found = queue.sheet.getRange(2,column,queue.sheet.getLastRow()-1,1)
    .createTextFinder(id).matchEntireCell(true).useRegularExpression(false).findNext();
  if (!found) return null;
  const rowNumber = found.getRow();
  const row = queue.sheet.getRange(rowNumber,1,1,queue.headers.length).getDisplayValues()[0];
  const values = {};
  queue.headers.forEach(function(header,index){values[header]=row[index] || '';});
  return {sheet:queue.sheet,headers:queue.headers,rowNumber:rowNumber,values:values};
}

function update_(sheet,rowNumber,headers,updates) {
  Object.keys(updates).forEach(function(field){
    const index=headers.indexOf(field);
    if(index === -1) throw new Error('Review service is not configured.');
    sheet.getRange(rowNumber,index+1).setValue(updates[field]);
  });
}

function response_(row, reviewer) {
  return {
    submissionUuid:row.submission_uuid, staffName:row.staff_display_name || nameFromEmail_(row.staff_email),
    staffEmail:row.staff_email, department:row.department_name || '',
    absenceType:title_(row.absence_type), startDate:friendlyDate_(row.start_date),
    endDate:row.end_date && row.end_date !== row.start_date ? friendlyDate_(row.end_date) : '',
    duration:DURATION_LABELS[row.duration_mode] || row.duration_mode, days:row.days_value || '',
    startTime:friendlyTime_(row.start_time), note:row.notes || 'No note provided.',
    status:String(row.workflow_status || 'pending').toLowerCase(), reviewer:reviewer,
    reviewedBy:row.reviewed_by || '', reviewedAt:row.reviewed_at ? friendlyTimestamp_(row.reviewed_at) : '',
    decisionNote:row.decision_note || ''
  };
}

function title_(value){return String(value || '').replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});}
function nameFromEmail_(email){return title_(String(email || '').split('@')[0].replace(/[.-]/g,' '));}
function friendlyDate_(iso){const p=String(iso||'').split('-').map(Number);if(p.length!==3)return '';return Utilities.formatDate(new Date(p[0],p[1]-1,p[2]),Session.getScriptTimeZone(),'EEEE, MMMM d, yyyy');}
function friendlyTime_(value){const m=String(value||'').match(/^(\d{2}):(\d{2})$/);if(!m)return 'All day';const h=Number(m[1]);return ((h+11)%12+1)+':'+m[2]+' '+(h>=12?'PM':'AM');}
function friendlyTimestamp_(iso){const d=new Date(iso);return isNaN(d.getTime())?'':Utilities.formatDate(d,Session.getScriptTimeZone(),"MMMM d, yyyy 'at' h:mm a");}
