import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { loginWithEmail } from '../services/api';
import { colors } from '../theme';

export default function LoginScreen({ navigation, onLogin }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const login = async () => {
    if (!email.trim() || !password) return setError('Enter your email and password.');
    setLoading(true);
    try { const data = await loginWithEmail(email.trim(), password); onLogin(data.user); } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  return (
    <View style={styles.page}>
      <View style={styles.intro}>
        <View style={styles.mark}><Ionicons name="layers" size={30} color={colors.primary} /></View>
        <Text style={styles.brand}>QUANTUM SWARM</Text>
        <Text style={styles.headline}>Autonomous engineering, under your control.</Text>
        <Text style={styles.copy}>Plan projects with an AI CEO, supervise the agent swarm, and review every task, artifact, quality gate, and execution log.</Text>
        <View style={styles.points}><Point icon="grid-outline" text="Portfolio delivery console" /><Point icon="hardware-chip-outline" text="Live agent supervision" /><Point icon="shield-checkmark-outline" text="Truthful quality gates" /></View>
      </View>
      <View style={styles.formSide}>
        <View style={styles.form}>
          <Text style={styles.title}>Welcome back</Text><Text style={styles.subtitle}>Sign in to your engineering control center.</Text>
          {!!error && <Text style={styles.error}>{error}</Text>}
          <Text style={styles.label}>Email</Text><TextInput value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="you@company.com" placeholderTextColor={colors.textDim} style={styles.input} />
          <Text style={styles.label}>Password</Text><View><TextInput value={password} onChangeText={setPassword} secureTextEntry={!show} placeholder="At least 8 characters" placeholderTextColor={colors.textDim} style={styles.input} /><TouchableOpacity style={styles.eye} onPress={() => setShow(!show)}><Ionicons name={show ? 'eye-off-outline' : 'eye-outline'} size={18} color={colors.textMuted} /></TouchableOpacity></View>
          <TouchableOpacity style={styles.button} onPress={login} disabled={loading}>{loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Sign in</Text>}</TouchableOpacity>
          <TouchableOpacity style={styles.local} onPress={() => onLogin({ id: 'guest', name: 'Local Operator', email: '' })}><Ionicons name="desktop-outline" size={17} color={colors.primary} /><Text style={styles.localText}>Open local workspace</Text></TouchableOpacity>
          <TouchableOpacity onPress={() => navigation.navigate('Register')}><Text style={styles.link}>New to Quantum Swarm? <Text style={{ color: colors.primary, fontWeight: '800' }}>Create account</Text></Text></TouchableOpacity>
        </View>
      </View>
    </View>
  );
}

function Point({ icon, text }) { return <View style={styles.point}><Ionicons name={icon} size={18} color={colors.success} /><Text style={styles.pointText}>{text}</Text></View>; }
const styles = StyleSheet.create({
  page: { flex: 1, flexDirection: 'row', backgroundColor: colors.bg }, intro: { flex: 1.15, padding: 52, justifyContent: 'center', borderRightWidth: 1, borderRightColor: colors.border }, mark: { width: 54, height: 54, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primarySoft, borderWidth: 1, borderColor: colors.primary }, brand: { color: colors.text, fontSize: 14, fontWeight: '900', letterSpacing: 1.2, marginTop: 16 }, headline: { color: colors.text, fontSize: 34, lineHeight: 42, fontWeight: '800', maxWidth: 520, marginTop: 30 }, copy: { color: colors.textMuted, fontSize: 14, lineHeight: 22, maxWidth: 520, marginTop: 14 }, points: { marginTop: 28 }, point: { flexDirection: 'row', alignItems: 'center', marginBottom: 13 }, pointText: { color: colors.textMuted, fontSize: 13, marginLeft: 10 },
  formSide: { flex: 0.85, alignItems: 'center', justifyContent: 'center', padding: 24 }, form: { width: '100%', maxWidth: 410 }, title: { color: colors.text, fontSize: 26, fontWeight: '800' }, subtitle: { color: colors.textMuted, fontSize: 13, marginTop: 7, marginBottom: 24 }, error: { color: colors.danger, backgroundColor: '#29161c', borderWidth: 1, borderColor: '#59252d', borderRadius: 7, padding: 10, fontSize: 11, marginBottom: 15 }, label: { color: colors.textMuted, fontSize: 11, fontWeight: '700', marginBottom: 7 }, input: { height: 44, color: colors.text, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 12, marginBottom: 15, outlineStyle: 'none' }, eye: { position: 'absolute', right: 12, top: 12 }, button: { height: 44, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primary, borderRadius: 8, marginTop: 4 }, buttonText: { color: '#fff', fontSize: 13, fontWeight: '800' }, local: { height: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.borderStrong, borderRadius: 8, marginTop: 10 }, localText: { color: colors.text, fontSize: 12, fontWeight: '700', marginLeft: 7 }, link: { color: colors.textMuted, fontSize: 11, textAlign: 'center', marginTop: 20 },
});
