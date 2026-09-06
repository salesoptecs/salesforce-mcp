// Copy only the audited runtime into the package. Never copy the site or its secrets.
const fs = require('node:fs');
const path = require('node:path');
fs.mkdirSync(path.join(__dirname, 'runtime'), {recursive: true});
const siteSource = path.join(__dirname, '../../static/downloads/salesforce_mcp_server.py');
const source = fs.existsSync(siteSource) ? siteSource : path.join(__dirname, '../../salesforce_mcp_server.py');
fs.copyFileSync(source,
  path.join(__dirname, 'runtime/salesforce_mcp_server.py'));
