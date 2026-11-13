import { HOME } from "../auth.js";
import { mountShell } from "../ui/shell.js";

const me = await mountShell({ public: true });
if (me) location.replace(HOME[me.role]);
