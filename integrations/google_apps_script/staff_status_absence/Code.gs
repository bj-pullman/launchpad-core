const SCRIPT_PROPERTY_API_URL = 'LAUNCHPAD_API_URL';
const SCRIPT_PROPERTY_API_SECRET = 'LAUNCHPAD_API_SECRET';

const ABSENCE_TYPES = [
  { value: 'sick', label: 'Sick' },
  { value: 'vacation', label: 'Vacation' },
  { value: 'personal', label: 'Personal' },
  { value: 'other', label: 'Other' }
];

const DURATION_OPTIONS = [
  { value: 'quarter_day', label: '2 hours', requiresStartTime: true, requiresEndDate: false, requiresDays: false },
  { value: 'half_day', label: '4 hours', requiresStartTime: true, requiresEndDate: false, requiresDays: false },
  { value: 'three_quarter_day', label: '6 hours', requiresStartTime: true, requiresEndDate: false, requiresDays: false },
  { value: 'full_day', label: '8 hours / Full regular day', requiresStartTime: false, requiresEndDate: false, requiresDays: false },
  { value: 'summer_2_hours', label: 'Summer - 2 hours', requiresStartTime: true, requiresEndDate: false, requiresDays: false },
  { value: 'summer_4_hours', label: 'Summer - 4 hours', requiresStartTime: true, requiresEndDate: false, requiresDays: false },
  { value: 'summer_6_hours', label: 'Summer - 6 hours', requiresStartTime: true, requiresEndDate: false, requiresDays: false },
  { value: 'summer_8_hours', label: 'Summer - 8 hours', requiresStartTime: false, requiresEndDate: false, requiresDays: false },
  { value: 'summer_full_day', label: 'Summer full day - 10 hours / 1.25 days', requiresStartTime: false, requiresEndDate: false, requiresDays: false },
  { value: 'multi_day', label: 'Multiple Days', requiresStartTime: false, requiresEndDate: true, requiresDays: true }
];

function doGet() {
  return HtmlService
    .createTemplateFromFile('Index')
    .evaluate()
    .setTitle('Staff Absence Request')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

function getFormConfig() {
  return {
    activeUserEmail: getActiveUserEmail_(),
    absenceTypes: ABSENCE_TYPES,
    durationOptions: DURATION_OPTIONS
  };
}

function submitAbsenceRequest(formPayload) {
  const payload = normalizePayload_(formPayload || {});
  const properties = PropertiesService.getScriptProperties();
  const apiUrl = (properties.getProperty(SCRIPT_PROPERTY_API_URL) || '').trim();
  const apiSecret = (properties.getProperty(SCRIPT_PROPERTY_API_SECRET) || '').trim();

  if (!apiUrl) {
    throw new Error('The Launchpad API URL is not configured.');
  }

  if (!apiSecret) {
    throw new Error('The Launchpad API secret is not configured.');
  }

  const response = UrlFetchApp.fetch(apiUrl, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: 'Bearer ' + apiSecret
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });

  const statusCode = response.getResponseCode();
  const bodyText = response.getContentText() || '{}';
  let body;

  try {
    body = JSON.parse(bodyText);
  } catch (error) {
    body = {};
  }

  if (statusCode >= 200 && statusCode < 300 && body.ok) {
    return {
      ok: true,
      requestId: body.request_id,
      duplicate: !!body.duplicate,
      status: body.status || 'pending'
    };
  }

  throw new Error(body.error || 'Unable to submit your absence request.');
}

function normalizePayload_(input) {
  const staffEmail = normalizeEmail_(input.staff_email || input.email);
  const absenceType = normalizeChoice_(input.absence_type, ABSENCE_TYPES);
  const durationMode = normalizeChoice_(input.duration_mode, DURATION_OPTIONS);
  const startDate = normalizeIsoDate_(input.start_date);
  const duration = DURATION_OPTIONS.find(function(option) {
    return option.value === durationMode;
  });

  if (!staffEmail) {
    throw new Error('Enter a valid district email address.');
  }

  if (!startDate) {
    throw new Error('Choose a valid start date.');
  }

  let endDate = startDate;
  let daysValue = null;

  if (duration.value === 'multi_day') {
    endDate = normalizeIsoDate_(input.end_date);
    daysValue = Number(input.days_value);

    if (!endDate) {
      throw new Error('Choose a valid end date.');
    }

    if (endDate < startDate) {
      throw new Error('End date cannot be before start date.');
    }

    if (!Number.isFinite(daysValue) || daysValue <= 0) {
      throw new Error('Enter the total number of absence days.');
    }
  }

  const startTime = normalizeTime_(input.start_time);
  if (duration.requiresStartTime && !startTime) {
    throw new Error('Choose a start time for partial-day absences.');
  }

  return {
    submission_uuid: String(input.submission_uuid || Utilities.getUuid()),
    staff_email: staffEmail,
    absence_type: absenceType,
    duration_mode: durationMode,
    start_date: startDate,
    end_date: endDate,
    start_time: startTime,
    days_value: daysValue,
    note: String(input.note || '').trim()
  };
}

function normalizeEmail_(value) {
  const email = String(value || '').trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return '';
  }
  return email;
}

function normalizeChoice_(value, options) {
  const normalized = String(value || '').trim();
  const validValues = options.map(function(option) {
    return option.value;
  });

  if (validValues.indexOf(normalized) === -1) {
    throw new Error('Choose a valid option.');
  }

  return normalized;
}

function normalizeIsoDate_(value) {
  const normalized = String(value || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(normalized)) {
    return '';
  }
  return normalized;
}

function normalizeTime_(value) {
  const normalized = String(value || '').trim();
  if (!normalized) {
    return '';
  }

  if (!/^\d{2}:\d{2}$/.test(normalized)) {
    return '';
  }

  return normalized;
}

function getActiveUserEmail_() {
  try {
    return Session.getActiveUser().getEmail() || '';
  } catch (error) {
    return '';
  }
}
