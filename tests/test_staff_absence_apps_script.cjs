const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'staff-absence-public-form', 'Code.gs'), 'utf8');
const UUID = '164a70c6-73d5-4e61-a312-cb9019f7f451';
const headers = [
  'submission_uuid','submitted_at','staff_email','absence_type','duration_mode','start_date','end_date',
  'start_time','days_value','notes','processing_status','processing_started_at','processed_at',
  'launchpad_request_id','processing_error','processing_attempts','last_processing_attempt_at',
  'processing_claim_id','staff_display_name','department_name','approval_manager_email','workflow_status',
  'reviewed_by','reviewed_at','decision_note','launchpad_sync_status','launchpad_synced_at',
  'launchpad_sync_error','decision_claim_id'
];
const initial = Object.fromEntries(headers.map(header => [header, '']));
Object.assign(initial, {
  submission_uuid: UUID, staff_email: 'employee@sheridanschools.org', staff_display_name: 'Employee One',
  department_name: 'Technology', approval_manager_email: 'manager@sheridanschools.org',
  absence_type: 'sick', duration_mode: 'full_day', start_date: '2026-09-17', end_date: '2026-09-17',
  notes: 'Testing', processing_status: 'processed', workflow_status: 'pending', launchpad_sync_status: 'synced'
});
const rows = [headers.map(header => initial[header])];
let activeEmail = '';
let sheetOpenCount = 0;
let generatedUuid = '264a70c6-73d5-4e61-a312-cb9019f7f452';
const properties = {
  ABSENCE_SUBMISSION_SHEET_ID: 'sheet-id',
  APPROVER_EMAILS: 'manager@sheridanschools.org',
  GLOBAL_APPROVER_EMAILS: 'admin@sheridanschools.org,personal.reviewer@gmail.com'
};

function range(row, column, rowCount, columnCount) {
  return {
    getDisplayValues() {
      if (row === 1) return [headers.slice(column - 1, column - 1 + columnCount)];
      return rows.slice(row - 2, row - 2 + rowCount)
        .map(values => values.slice(column - 1, column - 1 + columnCount));
    },
    createTextFinder(value) {
      return {
        matchEntireCell() { return this; }, useRegularExpression() { return this; },
        findNext() {
          const offset = rows.findIndex(values => String(values[column - 1]) === String(value));
          return offset < 0 ? null : { getRow: () => offset + 2 };
        }
      };
    },
    setValue(value) { rows[row - 2][column - 1] = value; return this; },
    setValues(values) {
      if (row === 1) throw new Error('Unexpected header mutation during test.');
      rows[row - 2] = values[0].slice();
      return this;
    },
    setNumberFormat() { return this; }, setFontWeight() { return this; }, setBackground() { return this; }
  };
}

const sheet = {
  getLastRow: () => rows.length + 1,
  getLastColumn: () => headers.length,
  getRange: range,
  getName: () => 'Absence Requests',
  setFrozenRows() {}
};
const htmlOutput = file => ({
  file, setTitle() { return this; }, addMetaTag() { return this; }
});
const context = {
  console,
  Session: {
    getActiveUser: () => ({ getEmail: () => activeEmail }),
    getScriptTimeZone: () => 'America/Chicago'
  },
  PropertiesService: { getScriptProperties: () => ({ getProperty: key => properties[key] || '' }) },
  Utilities: { getUuid: () => generatedUuid, formatDate: () => 'formatted' },
  HtmlService: {
    createHtmlOutputFromFile: htmlOutput,
    createTemplateFromFile(file) {
      return {
        file, requestId: '', signedInEmail: '', deniedTitle: '', deniedMessage: '',
        evaluate() {
          return Object.assign(htmlOutput(file), {
            requestId: this.requestId, signedInEmail: this.signedInEmail,
            deniedTitle: this.deniedTitle, deniedMessage: this.deniedMessage
          });
        }
      };
    }
  },
  LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
  SpreadsheetApp: {
    openById: () => { sheetOpenCount += 1; return { getSheetByName: () => sheet, insertSheet: () => sheet }; },
    flush() {}
  }
};
vm.createContext(context);
vm.runInContext(source, context);

assert.equal(context.doGet().file, 'Index', 'default doGet renders public intake');

const beforeGet = JSON.stringify(rows);
activeEmail = 'manager@sheridanschools.org';
assert.equal(context.doGet({ parameter: { action: 'review', id: UUID } }).file, 'Review');
assert.equal(JSON.stringify(rows), beforeGet, 'review GET never changes workflow state');
const assigned = context.getReviewRequest(UUID);
assert.equal(assigned.staffEmail, 'employee@sheridanschools.org');

activeEmail = '';
const opensBeforeAnonymousReview = sheetOpenCount;
assert.throws(() => context.getReviewRequest(UUID), /could not verify/);
assert.equal(sheetOpenCount, opensBeforeAnonymousReview, 'anonymous review fails before Sheet access');
const signInRequired = context.doGet({ parameter: { action: 'review', id: UUID } });
assert.equal(signInRequired.file, 'AccessDenied');
assert.equal(signInRequired.deniedTitle, 'Sign-in Required');
assert.equal(signInRequired.signedInEmail, '');
activeEmail = 'random.account@gmail.com';
assert.throws(() => context.getReviewRequest(UUID), /not authorized/);
const randomDenied = context.doGet({ parameter: { action: 'review', id: UUID } });
assert.equal(randomDenied.deniedTitle, 'Access Denied');
assert.equal(randomDenied.signedInEmail, 'random.account@gmail.com');
activeEmail = 'other@sheridanschools.org';
properties.APPROVER_EMAILS += ',other@sheridanschools.org';
assert.throws(() => context.getReviewRequest(UUID), /another reviewer/);
activeEmail = 'admin@sheridanschools.org';
assert.equal(context.getReviewRequest(UUID).staffEmail, 'employee@sheridanschools.org');
activeEmail = 'personal.reviewer@gmail.com';
assert.equal(context.getReviewRequest(UUID).staffEmail, 'employee@sheridanschools.org');

const workflowColumn = headers.indexOf('workflow_status');
activeEmail = '';
assert.throws(() => context.submitReviewDecision(UUID, 'approved', ''), /could not verify/);
assert.equal(rows[0][workflowColumn], 'pending');
activeEmail = 'other@sheridanschools.org';
assert.throws(() => context.submitReviewDecision(UUID, 'denied', ''), /another reviewer/);
assert.equal(rows[0][workflowColumn], 'pending');
activeEmail = 'manager@sheridanschools.org';
context.submitReviewDecision(UUID, 'approved', 'Approved in test', 'attacker@sheridanschools.org');
assert.equal(rows[0][workflowColumn], 'approved');
assert.equal(rows[0][headers.indexOf('reviewed_by')], 'manager@sheridanschools.org');

rows[0][workflowColumn] = 'pending';
rows[0][headers.indexOf('reviewed_by')] = '';
activeEmail = 'personal.reviewer@gmail.com';
context.submitReviewDecision(UUID, 'denied', 'Denied in test');
assert.equal(rows[0][workflowColumn], 'denied');
assert.equal(rows[0][headers.indexOf('reviewed_by')], 'personal.reviewer@gmail.com');

const beforeSubmitCount = rows.length;
context.submitAbsenceRequest({
  submission_uuid: generatedUuid, staff_email: 'newstaff@sheridanschools.org', absence_type: 'personal',
  duration_mode: 'full_day', start_date: '2026-09-20', end_date: '', start_time: '', days_value: '', notes: ''
});
assert.equal(rows.length, beforeSubmitCount + 1, 'anonymous intake still appends one request');
assert.equal(rows[1][workflowColumn], 'pending');
assert.equal(context.submitReviewDecision.length, 3, 'decision API accepts no reviewer identity argument');
assert.doesNotMatch(source, /input\.reviewer|reviewer_email.*input|input.*reviewer_email/);
console.log('Staff absence unified Apps Script tests passed.');
