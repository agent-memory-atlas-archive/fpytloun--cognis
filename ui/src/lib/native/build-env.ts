// Native assets are immutable publisher build inputs. Loading env.js from the
// selected server would execute remote code and cannot bootstrap an HTTPS WK
// document through a custom scheme. The web build retains its dynamic owner.
import * as env from '$env/static/public';
export { env };
