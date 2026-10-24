import { mount } from 'svelte';
import Fixture from './Fixture.svelte';
import '../../src/app.css';
import { auth } from '../../src/lib/stores/auth';
import { wsClient } from '../../src/lib/ws/client';

await auth.bootstrap();
if (new URLSearchParams(location.search).has('streaming')) wsClient.connect();
mount(Fixture, { target: document.getElementById('app')! });
