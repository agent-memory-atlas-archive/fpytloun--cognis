import { mount } from 'svelte';
import '../../../src/app.css';
import HistoryApp from './HistoryApp.svelte';

mount(HistoryApp, { target: document.getElementById('app')! });
