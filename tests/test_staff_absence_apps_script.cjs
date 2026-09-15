const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'staff-absence-review-form', 'Code.gs'), 'utf8');
const publicSource = fs.readFileSync(path.join(__dirname, '..', 'staff-absence-public-form', 'Code.gs'), 'utf8');
let activeEmail = '';
const properties = { APPROVER_EMAILS: 'manager@sheridanschools.org', GLOBAL_APPROVER_EMAILS: 'admin@sheridanschools.org' };
const context = {
  console,
  Session: { getActiveUser: () => ({ getEmail: () => activeEmail }), getScriptTimeZone: () => 'America/Chicago' },
  PropertiesService: { getScriptProperties: () => ({ getProperty: key => properties[key] || '' }) },
  Utilities: { getUuid: () => '164a70c6-73d5-4e61-a312-cb9019f7f451', formatDate: () => 'formatted' },
  HtmlService: {}, LockService: {}, SpreadsheetApp: {},
};
vm.createContext(context);
vm.runInContext(source, context);

const assigned = { approval_manager_email: 'manager@sheridanschools.org' };
activeEmail = '';
assert.throws(() => context.authorize_(assigned), /could not verify/);
activeEmail = 'other@sheridanschools.org';
assert.throws(() => context.authorize_(assigned), /not authorized/);
activeEmail = 'manager@sheridanschools.org';
assert.equal(context.authorize_(assigned), activeEmail);
activeEmail = 'admin@sheridanschools.org';
assert.equal(context.authorize_({ approval_manager_email: 'someone@sheridanschools.org' }), activeEmail);
properties.APPROVER_EMAILS = 'other@sheridanschools.org';
activeEmail = 'other@sheridanschools.org';
assert.throws(() => context.authorize_(assigned), /another reviewer/);

assert.match(source, /workflow_status/);
assert.match(source, /launchpad_sync_status/);
assert.match(source, /function submitReviewDecision/);
assert.doesNotMatch(source, /function doGet[\s\S]{0,500}submitReviewDecision\(/);
assert.doesNotMatch(publicSource, /getReviewRequest|submitReviewDecision|Session\.getActiveUser/);
console.log('Staff absence Apps Script authorization tests passed.');
