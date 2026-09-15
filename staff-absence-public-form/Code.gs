const SCRIPT_PROPERTY_SHEET_ID = 'ABSENCE_SUBMISSION_SHEET_ID';
const WORKSHEET_NAME = 'Absence Requests';
const MAX_NOTES_LENGTH = 1000;

const BASE_QUEUE_HEADERS = [
  'submission_uuid',
  'submitted_at',
  'staff_email',
  'absence_type',
  'duration_mode',
  'start_date',
  'end_date',
  'start_time',
  'days_value',
  'notes',
  'processing_status',
  'processing_started_at',
  'processed_at',
  'launchpad_request_id',
  'processing_error',
  'processing_attempts',
  'last_processing_attempt_at',
  'processing_claim_id'
];
const WORKFLOW_HEADERS = [
  'staff_display_name',
  'department_name',
  'approval_manager_email',
  'workflow_status',
  'reviewed_by',
  'reviewed_at',
  'decision_note',
  'launchpad_sync_status',
  'launchpad_synced_at',
  'launchpad_sync_error',
  'decision_claim_id'
];
const QUEUE_HEADERS = BASE_QUEUE_HEADERS.concat(WORKFLOW_HEADERS);

const ABSENCE_TYPES = [
  { value: 'sick', label: 'Sick' },
  { value: 'vacation', label: 'Vacation' },
  { value: 'personal', label: 'Personal' },
  { value: 'other', label: 'Other' }
];

const DURATION_OPTIONS = [
  { value: 'quarter_day', label: '2 hours', requiresStartTime: true },
  { value: 'half_day', label: '4 hours', requiresStartTime: true },
  { value: 'three_quarter_day', label: '6 hours', requiresStartTime: true },
  { value: 'full_day', label: '8 hours / Full regular day' },
  { value: 'summer_2_hours', label: 'Summer - 2 hours', requiresStartTime: true },
  { value: 'summer_4_hours', label: 'Summer - 4 hours', requiresStartTime: true },
  { value: 'summer_6_hours', label: 'Summer - 6 hours', requiresStartTime: true },
  { value: 'summer_8_hours', label: 'Summer - 8 hours' },
  { value: 'summer_full_day', label: 'Summer full day - 10 hours / 1.25 days' },
  { value: 'multi_day', label: 'Multiple Days', requiresEndDate: true, requiresDays: true }
];

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('Staff Absence Request')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function getFormConfig() {
  return {
    absenceTypes: ABSENCE_TYPES,
    durationOptions: DURATION_OPTIONS,
    submissionUuid: Utilities.getUuid()
  };
}

function newSubmissionUuid() {
  return Utilities.getUuid();
}

function initializeAbsenceRequestSheet_() {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const sheet = getOrCreateQueueSheet_();
    return { ok: true, worksheetName: sheet.getName(), headers: QUEUE_HEADERS.slice() };
  } finally {
    lock.releaseLock();
  }
}

function submitAbsenceRequest(input) {
  let payload;
  try {
    payload = normalizePayload_(input || {});
    const lock = LockService.getScriptLock();
    lock.waitLock(30000);
    try {
      const sheet = getOrCreateQueueSheet_();
      if (submissionExists_(sheet, payload.submission_uuid)) {
        return { ok: true, duplicate: true };
      }

      const headers = getHeaders_(sheet);
      const values = {
        submission_uuid: payload.submission_uuid, submitted_at: new Date().toISOString(),
        staff_email: payload.staff_email, absence_type: payload.absence_type,
        duration_mode: payload.duration_mode, start_date: payload.start_date,
        end_date: payload.end_date, start_time: payload.start_time,
        days_value: payload.days_value, notes: payload.notes,
        processing_status: 'pending', processing_attempts: 0,
        workflow_status: 'pending', launchpad_sync_status: 'pending'
      };
      const row = headers.map(function(header) { return values[header] === undefined ? '' : values[header]; });
      const target = sheet.getRange(sheet.getLastRow() + 1, 1, 1, headers.length);
      target.setNumberFormat('@');
      target.setValues([row]);
      SpreadsheetApp.flush();
      return { ok: true, duplicate: false };
    } finally {
      lock.releaseLock();
    }
  } catch (error) {
    console.error('Absence submission failed for UUID %s: %s',
      payload ? payload.submission_uuid : 'invalid', error && error.message ? error.message : 'unknown');
    throw new Error(isValidationMessage_(error && error.message)
      ? error.message
      : 'Your request could not be submitted. Please try again.');
  }
}

function getOrCreateQueueSheet_() {
  const spreadsheetId = (PropertiesService.getScriptProperties()
    .getProperty(SCRIPT_PROPERTY_SHEET_ID) || '').trim();
  if (!spreadsheetId) {
    throw new Error('The absence request service is not configured.');
  }

  const spreadsheet = SpreadsheetApp.openById(spreadsheetId);
  let sheet = spreadsheet.getSheetByName(WORKSHEET_NAME);
  if (!sheet) sheet = spreadsheet.insertSheet(WORKSHEET_NAME);

  if (sheet.getLastRow() === 0) {
    const headerRange = sheet.getRange(1, 1, 1, QUEUE_HEADERS.length);
    headerRange.setValues([QUEUE_HEADERS]);
    headerRange.setFontWeight('bold');
    headerRange.setBackground('#e8eef8');
    sheet.setFrozenRows(1);
  } else {
    const lastColumn = Math.max(sheet.getLastColumn(), 1);
    const existing = sheet.getRange(1, 1, 1, lastColumn).getDisplayValues()[0]
      .map(function(value) { return String(value || '').trim(); });
    if (existing.slice(0, BASE_QUEUE_HEADERS.length).join('\n') !== BASE_QUEUE_HEADERS.join('\n')) {
      throw new Error('The absence request service is not configured correctly.');
    }
    const missing = QUEUE_HEADERS.filter(function(header) { return existing.indexOf(header) === -1; });
    if (missing.length) {
      const startColumn = existing.length + 1;
      const range = sheet.getRange(1, startColumn, 1, missing.length);
      range.setValues([missing]);
      range.setFontWeight('bold');
      range.setBackground('#e8eef8');
    }
  }
  return sheet;
}

function getHeaders_(sheet) {
  return sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0]
    .map(function(value) { return String(value || '').trim(); });
}

function submissionExists_(sheet, submissionUuid) {
  if (sheet.getLastRow() < 2) return false;
  return !!sheet.getRange(2, 1, sheet.getLastRow() - 1, 1)
    .createTextFinder(submissionUuid)
    .matchEntireCell(true)
    .useRegularExpression(false)
    .findNext();
}

function normalizePayload_(input) {
  const submissionUuid = String(input.submission_uuid || '').trim().toLowerCase();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(submissionUuid)) {
    throw new Error('Please reload the form and try again.');
  }

  const staffEmail = String(input.staff_email || '').trim().toLowerCase();
  if (!/^[^\s@]+@sheridanschools\.org$/.test(staffEmail)) {
    throw new Error('Enter a valid @sheridanschools.org email address.');
  }

  const absenceType = normalizeChoice_(input.absence_type, ABSENCE_TYPES, 'Choose an absence type.');
  const durationMode = normalizeChoice_(input.duration_mode, DURATION_OPTIONS, 'Choose a duration.');
  const duration = DURATION_OPTIONS.find(function(option) { return option.value === durationMode; });
  const startDate = normalizeIsoDate_(input.start_date);
  if (!startDate) throw new Error('Choose a valid start date.');

  let endDate = startDate;
  let daysValue = '';
  if (duration.requiresEndDate) {
    endDate = normalizeIsoDate_(input.end_date);
    if (!endDate) throw new Error('Choose a valid end date.');
    if (endDate < startDate) throw new Error('End date cannot be before start date.');
  }
  if (duration.requiresDays) {
    daysValue = Number(input.days_value);
    if (!Number.isFinite(daysValue) || daysValue <= 0) {
      throw new Error('Enter the total number of absence days.');
    }
  }

  const suppliedTime = String(input.start_time || '').trim();
  const startTime = normalizeTime_(suppliedTime);
  if (suppliedTime && !startTime) throw new Error('Choose a valid start time.');
  if (duration.requiresStartTime && !startTime) {
    throw new Error('Choose a start time for partial-day absences.');
  }

  const notes = String(input.notes || '').trim();
  if (notes.length > MAX_NOTES_LENGTH) throw new Error('Notes cannot exceed 1000 characters.');

  return {
    submission_uuid: submissionUuid,
    staff_email: staffEmail,
    absence_type: absenceType,
    duration_mode: durationMode,
    start_date: startDate,
    end_date: endDate,
    start_time: startTime,
    days_value: daysValue,
    notes: notes
  };
}

function normalizeChoice_(value, options, message) {
  const normalized = String(value || '').trim();
  if (!options.some(function(option) { return option.value === normalized; })) throw new Error(message);
  return normalized;
}

function normalizeIsoDate_(value) {
  const normalized = String(value || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(normalized)) return '';
  const parts = normalized.split('-').map(Number);
  const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  return date.getUTCFullYear() === parts[0] && date.getUTCMonth() === parts[1] - 1 &&
    date.getUTCDate() === parts[2] ? normalized : '';
}

function normalizeTime_(value) {
  const normalized = String(value || '').trim();
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(normalized)) return '';
  return normalized;
}

function isValidationMessage_(message) {
  return /^(Please reload|Enter|Choose|End date|Notes cannot)/.test(String(message || ''));
}
