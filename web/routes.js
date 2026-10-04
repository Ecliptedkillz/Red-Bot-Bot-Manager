/* Shared by the browser and the route regression tests. */
(function (root) {
  function parseRoute(pathname) {
    const path = pathname.replace(/\/+$/, '') || '/';
    const globals = {'/':'overview','/admin':'admin','/cogs':'cogs','/logs':'logs','/bots/new':'create','/bots/import':'import','/cogs/new':'upload'};
    if (globals[path]) return {view:globals[path],botId:null};
    const match = path.match(/^\/bots\/([a-f0-9]{12})(?:\/(console|cogs|settings)(?:\/([^/]+)\/settings)?)?$/);
    if (!match || (match[3] && match[2] !== 'cogs')) return {view:'notfound',botId:null};
    let module;
    try { module = match[3] ? decodeURIComponent(match[3]) : null; } catch { return {view:'notfound',botId:null}; }
    return {botId:match[1],view:module?'cogsettings':(match[2]==='console'?'logs':match[2]||'bot'),module};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {parseRoute};
  else root.PortalRoutes = {parseRoute};
})(globalThis);
