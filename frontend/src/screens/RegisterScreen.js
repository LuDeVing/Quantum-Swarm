import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { registerWithEmail } from '../services/api';
import { colors } from '../theme';

export default function RegisterScreen({ navigation, onLogin }) {
  const [form, setForm] = useState({ name: '', email: '', password: '', confirm: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const register = async () => {
    if (!form.name.trim() || !form.email.trim() || !form.password) return setError('Complete every field.');
    if (form.password.length < 8) return setError('Password must be at least 8 characters.');
    if (form.password !== form.confirm) return setError('Passwords do not match.');
    setLoading(true);
    try { const data = await registerWithEmail(form.name.trim(), form.email.trim(), form.password); onLogin(data.user); } catch (e) { setError(e.message); } finally { setLoading(false); }
  };
  return <ScrollView style={styles.page} contentContainerStyle={styles.content}><View style={styles.form}><View style={styles.mark}><Ionicons name="layers" size={24} color={colors.primary} /></View><Text style={styles.title}>Create your control center</Text><Text style={styles.subtitle}>Set up an account for private engineering projects.</Text>{!!error && <Text style={styles.error}>{error}</Text>}<Field label="Name" value={form.name} onChangeText={(v) => set('name', v)} placeholder="Jane Doe" /><Field label="Email" value={form.email} onChangeText={(v) => set('email', v)} placeholder="you@company.com" autoCapitalize="none" /><Field label="Password" value={form.password} onChangeText={(v) => set('password', v)} placeholder="At least 8 characters" secureTextEntry /><Field label="Confirm password" value={form.confirm} onChangeText={(v) => set('confirm', v)} placeholder="Repeat password" secureTextEntry /><TouchableOpacity style={styles.button} onPress={register} disabled={loading}>{loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Create account</Text>}</TouchableOpacity><TouchableOpacity onPress={() => navigation.navigate('Login')}><Text style={styles.link}>Already have an account? <Text style={{ color: colors.primary, fontWeight: '800' }}>Sign in</Text></Text></TouchableOpacity></View></ScrollView>;
}
function Field({ label, ...props }) { return <View><Text style={styles.label}>{label}</Text><TextInput {...props} placeholderTextColor={colors.textDim} style={styles.input} /></View>; }
const styles = StyleSheet.create({ page: { flex: 1, backgroundColor: colors.bg }, content: { minHeight: '100%', alignItems: 'center', justifyContent: 'center', padding: 24 }, form: { width: '100%', maxWidth: 430, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: 24 }, mark: { width: 44, height: 44, borderRadius: 10, backgroundColor: colors.primarySoft, borderWidth: 1, borderColor: colors.primary, alignItems: 'center', justifyContent: 'center' }, title: { color: colors.text, fontSize: 23, fontWeight: '800', marginTop: 18 }, subtitle: { color: colors.textMuted, fontSize: 12, marginTop: 6, marginBottom: 20 }, error: { color: colors.danger, backgroundColor: '#29161c', borderRadius: 7, padding: 10, fontSize: 11, marginBottom: 15 }, label: { color: colors.textMuted, fontSize: 11, fontWeight: '700', marginBottom: 6 }, input: { height: 43, color: colors.text, backgroundColor: colors.bg, borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 12, marginBottom: 13, outlineStyle: 'none' }, button: { height: 44, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primary, borderRadius: 8, marginTop: 5 }, buttonText: { color: '#fff', fontWeight: '800', fontSize: 13 }, link: { color: colors.textMuted, fontSize: 11, textAlign: 'center', marginTop: 18 } });
