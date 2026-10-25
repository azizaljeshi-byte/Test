/**
 * StockWatch paper trading: the Google Sheet side. Paste into Extensions > Apps Script on the paper-trading Sheet.
 * Then: Project Settings > Script properties > add TOKEN (any long random string; the same one goes in the app's secrets as
 * STOCKWATCH_PAPER_TOKEN). Deploy > New deployment > Web app > Execute as: Me, Who has access: Anyone. Copy the web app link
 * into the app's secrets as STOCKWATCH_PAPER_WEBHOOK. Never put the token or the link in the repository.
 *
 * doPost saves the book and rewrites the Trades, Blocked buys and Daily report tabs; doGet gives the saved book back so a
 * rebooted app can carry on.
 */
function json_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
function tab_(name, header) {
  var ss = SpreadsheetApp.getActiveSpreadsheet(), sh = ss.getSheetByName(name) || ss.insertSheet(name);
  if (sh.getLastRow() === 0) { sh.appendRow(header); sh.setFrozenRows(1); sh.getRange(1, 1, 1, header.length).setFontWeight('bold'); }
  return sh;
}
function rewrite_(sh, header, rows) {
  sh.clearContents();
  sh.getRange(1, 1, 1, header.length).setValues([header]).setFontWeight('bold');
  if (rows.length) sh.getRange(2, 1, rows.length, header.length).setValues(rows);
}
function doGet(e) {
  var token = PropertiesService.getScriptProperties().getProperty('TOKEN');
  if (!token || !e.parameter || e.parameter.token !== token) return json_({ok: false, error: 'bad token'});
  var state = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('State');
  if (!state || state.getLastRow() < 2) return json_({ok: true, book: null});
  var parts = state.getRange(2, 1, state.getLastRow() - 1, 1).getValues().map(function (r) { return r[0]; });
  return json_({ok: true, book: JSON.parse(parts.join(''))});
}
function doPost(e) {
  var props = PropertiesService.getScriptProperties(), token = props.getProperty('TOKEN');
  var body = JSON.parse(e.postData.contents);
  if (!token || body.token !== token) return json_({ok: false, error: 'bad token'});
  var book = body.book || {}, rep = body.report || {};
  // The book is kept in cells on a hidden sheet (a cell holds about 50,000 characters, so it is split).
  var state = tab_('State', ['book json']); state.hideSheet();
  var json = JSON.stringify(book), chunks = [];
  for (var i = 0; i < json.length; i += 40000) chunks.push([json.substring(i, i + 40000)]);
  state.clearContents(); state.getRange(1, 1, 1, 1).setValue('book json');
  if (chunks.length) state.getRange(2, 1, chunks.length, 1).setValues(chunks);
  var tH = ['Trade id','Ticker','Opened (NY)','Entry price','Shares','Size $','Stop','Target 1','Entry reason','Status','Closed (NY)','Exit price','Exit reason','Result $','Result R','Worst dip %','Best run %'];
  var rows = (book.trades || []).map(function (t) { return [t.id, t.ticker, t.opened, t.entry, t.shares, t.size, t.stop, t.target1, t.reason, t.status, t.closed || '', t.exit || '', t.exit_reason || '', t.result, t.r === null ? '' : t.r, t.worst, t.best]; });
  rewrite_(tab_('Trades', tH), tH, rows);
  var bH = ['Day','Time (NY)','Ticker','Price then','Reason'];
  rewrite_(tab_('Blocked buys', bH), bH, (book.blocked || []).map(function (b) { return [b.day, b.time, b.ticker, b.price, b.reason]; }));
  if (rep.day) {
    var dH = ['Date (NY)','Trades opened','Trades closed','Wins','Losses','Win rate','Average R','Result $','Account','Buys blocked','Verdict'];
    var ds = tab_('Daily report', dH), last = ds.getLastRow();
    var row = [rep.day, rep.opened, rep.closed, rep.wins, rep.losses, rep.win_rate === null ? '' : rep.win_rate, rep.avg_r === null ? '' : rep.avg_r, rep.result, rep.equity, rep.blocked, rep.verdict];
    if (last > 1 && ds.getRange(last, 1).getDisplayValue() === rep.day) ds.getRange(last, 1, 1, row.length).setValues([row]); else ds.appendRow(row);
  }
  return json_({ok: true});
}
